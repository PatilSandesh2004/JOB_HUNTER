from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from ai_service.app.database.session import get_db
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.job import NormalizedJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/", response_model=List[NormalizedJob])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    try:
        repo = JobRepository(db)
        db_jobs = await repo.list_jobs()
        results = []
        for j in db_jobs:
            results.append(
                NormalizedJob(
                    id=j.id,
                    title=j.title,
                    company=j.company,
                    company_id=j.company_id,
                    description=j.description or "",
                    location=j.location or "Unknown",
                    country=j.country or "Unknown",
                    city=j.city,
                    workplace_type=j.workplace_type or "UNKNOWN",
                    remote_scope=j.remote_scope or "UNKNOWN",
                    employment_type=j.employment_type or "Full-time",
                    salary_min=j.salary_min,
                    salary_max=j.salary_max,
                    salary_currency=j.salary_currency,
                    experience_required=j.experience_required,
                    required_skills=j.required_skills or [],
                    preferred_skills=j.preferred_skills or [],
                    visa_sponsorship=j.visa_sponsorship or {"status": "UNKNOWN"},
                    relocation=j.relocation or False,
                    application_url=j.application_url,
                    source=j.source,
                    source_job_id=j.source_job_id,
                    posted_at=j.posted_at,
                    scraped_at=j.scraped_at,
                )
            )
        return results
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch jobs: {str(e)}",
        )
