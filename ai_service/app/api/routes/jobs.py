from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.api.deps import get_job_recheck_service
from ai_service.app.core.config import settings
from ai_service.app.database.session import get_db
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.match import JobWithMatch
from ai_service.app.services.jobs.recheck_service import JobRecheckService
from ai_service.app.services.matching.matching_engine import MatchingEngineService

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
async def rescore_jobs(limit: int = Query(200, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    """Re-run matching for every stored job (e.g. after the profile changed); returns the top `limit`."""
    repo = JobRepository(db)
    candidate = await CandidateRepository(db).get_active()
    if candidate is not None:
        matcher = MatchingEngineService()
        async for batch in repo.iter_batches():
            await repo.upsert_many(
                [JobWithMatch(job=i.job, match=matcher.evaluate_match(candidate, i.job)) for i in batch]
            )
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
