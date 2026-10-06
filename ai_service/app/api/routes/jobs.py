from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.database.session import get_db
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.match import JobWithMatch
from ai_service.app.services.matching.matching_engine import MatchingEngineService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobWithMatch])
async def list_jobs(limit: int = Query(200, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    return await JobRepository(db).list_all(limit)


@router.post("/rescore", response_model=list[JobWithMatch])
async def rescore_jobs(db: AsyncSession = Depends(get_db)):
    """Re-run matching for stored jobs, e.g. after the profile changed."""
    repo = JobRepository(db)
    items = await repo.list_all(limit=1000)
    candidate = await CandidateRepository(db).get_active()
    if candidate is None:
        return items
    matcher = MatchingEngineService()
    rescored = [JobWithMatch(job=i.job, match=matcher.evaluate_match(candidate, i.job)) for i in items]
    await repo.upsert_many(rescored)
    return await repo.list_all(limit=1000)


@router.delete("", status_code=200)
async def clear_jobs(db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    return {"deleted": await JobRepository(db).clear()}
