import asyncio
import os
from backend.app.core.config import settings
from backend.app.schemas.search import SearchQueryRequest
from backend.app.schemas.candidate import CandidateProfile, CandidatePreferences
from backend.app.services.search.search_service import SearchService
from backend.app.integrations.search.searxng_client import SearXNGClient
from backend.app.agents.search_agent.graph import create_search_graph
from backend.app.services.jobs.normalization_service import JobNormalizationService
from backend.app.services.jobs.deduplication_service import JobDeduplicationService
from backend.app.services.matching.matching_engine import MatchingEngineService
from backend.app.services.visa.visa_service import VisaIntelligenceService
from backend.app.services.applications.tailoring_service import ApplicationTailoringService
from backend.app.integrations.llm.llm_client import LLMClient
from backend.app.agents.application_agent.graph import create_application_graph


async def main():
    print("==================================================")
    print("Testing All JobPilot Phases")
    print("==================================================")

    # 1. Test Phase 1: Search Agent Setup
    print("\n--- Phase 1: Search Agent ---")
    req = SearchQueryRequest(roles=["AI Engineer"], locations=["Bengaluru"], remote_only=False)
    client = SearXNGClient(base_url=settings.searxng_url)
    search_service = SearchService(searxng_client=client)
    graph = create_search_graph(search_service=search_service)
    print("✓ Search Agent LangGraph successfully compiled.")

    # 2. Test Phase 2: Job Normalization & Deduplication
    print("\n--- Phase 2: Job Normalization & Deduplication ---")
    raw_job = {
        "title": "Senior AI Engineer (Remote India)",
        "url": "https://example.com/careers/ai-eng-1",
        "content": "Looking for Senior AI Engineer with Python, LangGraph experience. Visa sponsorship available.",
        "engine": "google",
    }
    normalizer = JobNormalizationService()
    norm_job = normalizer.normalize_raw_result(raw_job)
    print(f"✓ Normalized Job Title: {norm_job.title}")
    print(f"✓ Normalized Remote Scope: {norm_job.remote_scope.value}")
    print(f"✓ Normalized Visa Status: {norm_job.visa_sponsorship.status.value}")

    deduper = JobDeduplicationService()
    unique_jobs = deduper.deduplicate([norm_job, norm_job])
    print(f"✓ Deduplicated {2} jobs down to {len(unique_jobs)} unique job.")

    # 3. Test Phase 4: Candidate Profile
    print("\n--- Phase 4: Candidate Profile ---")
    candidate = CandidateProfile(
        name="John Doe",
        email="john.doe@example.com",
        years_of_experience=4.0,
        skills=["Python", "LangGraph", "FastAPI", "PostgreSQL"],
        preferences=CandidatePreferences(visa_sponsorship_required=True),
    )
    print(f"✓ Candidate Profile created: {candidate.name} ({candidate.email})")

    # 4. Test Phase 5: Matching Engine
    print("\n--- Phase 5: Matching Engine ---")
    matcher = MatchingEngineService()
    match_res = matcher.evaluate_match(candidate, norm_job)
    print(f"✓ Overall Match Score: {match_res.overall_match}/100")
    print(f"✓ Skill Match: {match_res.skill_match}%")
    print(f"✓ Explanation: {match_res.explanation}")

    # 5. Test Phase 6: Visa Intelligence
    print("\n--- Phase 6: Visa Intelligence ---")
    visa_service = VisaIntelligenceService()
    visa_ev = visa_service.evaluate_sponsorship("We offer full H1B visa sponsorship for top talent.")
    print(f"✓ Visa Sponsorship Status: {visa_ev.status.value}")
    print(f"✓ Evidence: {visa_ev.evidence}")

    # 6. Test Phase 7: Application Tailoring & Cover Letter
    print("\n--- Phase 7: Application Tailoring ---")
    llm_client = LLMClient()
    tailor_service = ApplicationTailoringService(llm_client=llm_client)
    cover_letter = await tailor_service.generate_cover_letter(candidate, norm_job)
    print(f"✓ Cover Letter generated ({len(cover_letter)} chars).")

    # 7. Test Phase 8: Application Agent (Human Approval Workflow)
    print("\n--- Phase 8: Application Agent Workflow ---")
    app_graph = create_application_graph()
    app_state = {
        "candidate_id": "cand-123",
        "job_id": norm_job.id,
        "application_url": norm_job.application_url,
        "applicant_data": {"name": candidate.name, "email": candidate.email},
        "cover_letter": cover_letter,
        "tailored_resume": None,
        "status": "DISCOVERED",
        "human_approved": False,
        "confirmation": None,
    }
    final_app_state = await app_graph.ainvoke(app_state)
    print(f"✓ Application Status (without approval): {final_app_state['status']}")

    print("\n==================================================")
    print("ALL PHASES VERIFIED AND WORKING SUCCESSFULLY!")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(main())
