from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.api.deps import (
    get_job_recheck_service,
    get_llm,
    get_resume_check_service,
    get_resume_library,
    get_searxng,
    get_semantic_matcher,
)
from ai_service.app.core.config import settings
from ai_service.app.database.session import get_db
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.models.resume_variant import ResumeVariantModel
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.connection_repository import ConnectionRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.match import JobWithMatch
from ai_service.app.services.jobs.normalization_service import refresh_requirements
from ai_service.app.services.jobs.recheck_service import JobRecheckService
from ai_service.app.services.matching.feedback import FeedbackModel
from ai_service.app.services.matching.matching_engine import MatchingEngineService
from ai_service.app.services.matching.reviewer import carry_over, profile_fingerprint
from ai_service.app.services.matching.semantic import SemanticMatcher
from ai_service.app.services.network.contacts import CompanyContactsService
from ai_service.app.services.network.outreach import OutreachWriter
from ai_service.app.services.resume.library import MAIN_LABEL, ResumeLibrary
from ai_service.app.services.resume.resume_check import ResumeCheckService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobWithMatch])
async def list_jobs(
    limit: int = Query(200, ge=1, le=1000),
    include_closed: bool = Query(False, description="Also return postings the job board reported closed"),
    hidden: bool = Query(False, description="Only the jobs you marked not interested"),
    db: AsyncSession = Depends(get_db),
):
    """Stored jobs, best match first. Hidden jobs and companies you blocked are left out."""
    return await JobRepository(db).list_all(limit, include_closed, await _blocked(db), hidden)


@router.post("/{job_id}/hide", status_code=204)
async def hide_job(job_id: str, db: AsyncSession = Depends(get_db)) -> None:
    """Not interested: hide this job now and in future search results."""
    if not await JobRepository(db).set_hidden(job_id, True):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")


@router.post("/{job_id}/unhide", status_code=204)
async def unhide_job(job_id: str, db: AsyncSession = Depends(get_db)) -> None:
    if not await JobRepository(db).set_hidden(job_id, False):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")


async def _blocked(db: AsyncSession) -> list[str]:
    candidate = await CandidateRepository(db).get_active()
    return candidate.preferences.blocked_companies if candidate else []


@router.post("/rescore", response_model=list[JobWithMatch])
async def rescore_jobs(
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    semantic: SemanticMatcher = Depends(get_semantic_matcher),
):
    """Re-run matching for every stored job (e.g. after the profile changed); returns the top `limit`.

    Skills and experience are re-read from each stored description first, so jobs saved by an older version
    are scored with the current parsers."""
    repo = JobRepository(db)
    candidate = await CandidateRepository(db).get_active()
    if candidate is not None:
        matcher, feedback, fingerprint = (
            MatchingEngineService(),
            await FeedbackModel.load(db),
            profile_fingerprint(candidate),
        )
        async for batch in repo.iter_batches():
            jobs = [refresh_requirements(i.job) for i in batch]
            similarity = await semantic.scores(candidate, jobs)
            rescored = [
                JobWithMatch(
                    job=job,
                    match=carry_over(
                        old.match,
                        matcher.evaluate_match(candidate, job, semantic=similarity.get(job.id), feedback=feedback),
                        fingerprint,
                    ),
                )
                for job, old in zip(jobs, batch, strict=True)
            ]
            await repo.upsert_many(rescored)
    return await repo.list_all(limit, blocked_companies=await _blocked(db))


@router.post("/recheck")
async def recheck_jobs(
    limit: int | None = Query(None, ge=1, le=500, description="Jobs to check (default: JOB_RECHECK_BATCH_SIZE)"),
    force: bool = Query(False, description="Also re-check jobs that were checked recently"),
    service: JobRecheckService = Depends(get_job_recheck_service),
) -> dict[str, int]:
    """Ask the job boards whether stored postings are still open; closed ones are hidden from the list."""
    return await service.recheck_stale(limit or settings.job_recheck_batch_size, 0 if force else None)


@router.delete("", status_code=200)
async def clear_jobs(db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """Delete stored jobs. Jobs you have an application for are kept so its history stays intact."""
    deleted, kept = await JobRepository(db).clear()
    return {"deleted": deleted, "kept": kept}


@router.get("/{job_id}/resume-check")
async def resume_check(
    job_id: str,
    variant_id: str | None = Query(None, description="A resume version; default: the version that fits best"),
    db: AsyncSession = Depends(get_db),
    library: ResumeLibrary = Depends(get_resume_library),
    checker: ResumeCheckService = Depends(get_resume_check_service),
) -> dict:
    """How well a resume fits this job: keyword coverage, readability for applicant tracking systems, tips."""
    job = await JobRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    model = await CandidateRepository(db).get_active_model()
    if model is None or not model.resume_path:
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload your resume first (Profile Settings)")
    label, text = MAIN_LABEL, await library.text_of(model.resume_path)
    variant = await db.get(ResumeVariantModel, variant_id) if variant_id else None
    if variant_id and variant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume version not found")
    if variant is None and (best := await library.best_for(db, model, job)) and best.variant_id:
        variant = await db.get(ResumeVariantModel, best.variant_id)
    if variant is not None:
        label, text = variant.label, variant.text
    return await checker.check(text, job, await CandidateRepository(db).get_active(), label)


# ---- network: people to contact at a company -----------------------------------------------------
@router.get("/company-contacts")
async def company_contacts(
    company: str = Query(..., min_length=1, max_length=200),
    job_title: str | None = Query(None, max_length=300),
    db: AsyncSession = Depends(get_db),
    searcher=Depends(get_searxng),
) -> dict:
    """Your LinkedIn connections at the company (from the CSV you uploaded) plus recruiters and team members
    found through web search."""
    result = await CompanyContactsService(searcher).find(company, job_title)
    candidate = await CandidateRepository(db).get_active()
    connections = await ConnectionRepository(db).find_by_company(candidate.id, company) if candidate else []
    result["connections"] = [
        {"first_name": c.first_name, "last_name": c.last_name, "position": c.position} for c in connections
    ]
    return result


@router.get("/{job_id}/insiders")
async def job_insiders(job_id: str, db: AsyncSession = Depends(get_db), searcher=Depends(get_searxng)) -> dict:
    """Contacts for the company behind a stored job, matched to its role."""
    job = await JobRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return await company_contacts(company=job.company, job_title=job.title, db=db, searcher=searcher)


class OutreachRequest(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(default="", max_length=200)
    contact_role: str = Field(default="", max_length=200)
    job_title: str = Field(default="", max_length=300)


@router.post("/outreach-message")
async def outreach_message(
    body: OutreachRequest, db: AsyncSession = Depends(get_db), llm: LLMClient = Depends(get_llm)
) -> dict[str, str]:
    """A LinkedIn connection note and a short message asking for a chat or referral (AI-written, or a template)."""
    candidate = await CandidateRepository(db).get_active()
    job_title = body.job_title or (candidate.current_role if candidate and candidate.current_role else "open role")
    return await OutreachWriter(llm).draft(candidate, body.company, body.contact_name, body.contact_role, job_title)
