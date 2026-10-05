import asyncio
import logging
from typing import List, Dict, Any
from ai_service.app.core.config import settings
from ai_service.app.schemas.search import SearchQueryRequest
from ai_service.app.schemas.candidate import CandidateProfile, CandidatePreferences
from ai_service.app.services.search.search_service import SearchService
from ai_service.app.integrations.search.searxng_client import SearXNGClient
from ai_service.app.services.jobs.normalization_service import JobNormalizationService
from ai_service.app.services.jobs.deduplication_service import JobDeduplicationService
from ai_service.app.services.matching.matching_engine import MatchingEngineService
from ai_service.app.integrations.vector.qdrant_client import QdrantVectorClient

logger = logging.getLogger("jobpilot.worker")
logging.basicConfig(level=logging.INFO)


class JobSearchWorker:
    """
    Background worker service that periodically executes job discovery,
    normalizes findings, deduplicates listings, indexes vectors, and runs candidate matching.
    """

    def __init__(self) -> None:
        self.searxng_client = SearXNGClient(base_url=settings.searxng_url)
        self.search_service = SearchService(searxng_client=self.searxng_client)
        self.normalizer = JobNormalizationService()
        self.deduper = JobDeduplicationService()
        self.matcher = MatchingEngineService()
        self.vector_client = QdrantVectorClient()
        self.is_running = False

    async def run_discovery_cycle(
        self,
        roles: List[str],
        locations: List[str],
        candidate: CandidateProfile,
        remote_only: bool = False
    ) -> Dict[str, Any]:
        logger.info(f"Starting background job discovery cycle for roles: {roles}, locations: {locations}")
        
        req = SearchQueryRequest(roles=roles, locations=locations, remote_only=remote_only)
        raw_results = await self.search_service.search_jobs(req)
        
        normalized_jobs = [self.normalizer.normalize_raw_result(r) for r in raw_results]
        unique_jobs = self.deduper.deduplicate(normalized_jobs)
        
        matched_results = []
        for job in unique_jobs:
            evaluation = self.matcher.evaluate_match(candidate, job)
            matched_results.append({
                "job": job.model_dump(),
                "match_evaluation": evaluation.model_dump()
            })
            
            # Index job vector in Qdrant if available
            try:
                self.vector_client.init_collection("jobs")
                dummy_vector = [0.0] * 384  # 384-dim placeholder embedding vector
                self.vector_client.upsert_job_vector(
                    collection_name="jobs",
                    job_id=job.id,
                    vector=dummy_vector,
                    payload={"title": job.title, "company": job.company, "location": job.location}
                )
            except Exception as e:
                logger.warning(f"Vector indexing skipped/failed: {e}")

        logger.info(f"Completed discovery cycle. Discovered {len(raw_results)} raw -> {len(unique_jobs)} unique jobs.")
        return {
            "total_raw": len(raw_results),
            "total_unique": len(unique_jobs),
            "jobs": matched_results
        }

    async def start_periodic_scheduler(
        self,
        interval_seconds: int = 3600,
        roles: List[str] = None,
        locations: List[str] = None,
        candidate: CandidateProfile = None
    ) -> None:
        if roles is None:
            roles = ["AI Engineer", "Software Engineer"]
        if locations is None:
            locations = ["Bengaluru", "Remote"]
        if candidate is None:
            candidate = CandidateProfile(
                name="System User",
                email="user@jobpilot.ai",
                years_of_experience=3.0,
                skills=["Python", "FastAPI", "LangGraph"],
                preferences=CandidatePreferences(visa_sponsorship_required=True)
            )

        self.is_running = True
        logger.info(f"Background Job Worker started with {interval_seconds}s interval.")
        
        while self.is_running:
            try:
                await self.run_discovery_cycle(roles=roles, locations=locations, candidate=candidate)
            except Exception as e:
                logger.error(f"Error during worker discovery cycle: {e}")
            await asyncio.sleep(interval_seconds)

    def stop(self) -> None:
        self.is_running = False
        logger.info("Background Job Worker stopped.")


if __name__ == "__main__":
    worker = JobSearchWorker()
    default_candidate = CandidateProfile(
        name="Test Worker Candidate",
        email="test@jobpilot.ai",
        years_of_experience=4.0,
        skills=["Python", "LangGraph", "FastAPI"],
        preferences=CandidatePreferences(visa_sponsorship_required=True)
    )
    res = asyncio.run(worker.run_discovery_cycle(
        roles=["AI Engineer"],
        locations=["Bengaluru"],
        candidate=default_candidate
    ))
    print(f"Worker cycle result summary: Discovered {res['total_unique']} unique jobs.")
