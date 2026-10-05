from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from ai_service.app.models.job import JobModel
from ai_service.app.schemas.job import NormalizedJob


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Persistence method saving a normalized job to PostgreSQL.
    async def create_or_update(self, job: NormalizedJob) -> JobModel:
        stmt = select(JobModel).where(JobModel.application_url == job.application_url)
        result = await self.session.execute(stmt)
        existing = result.scalars().first()

        if existing:
            existing.title = job.title
            existing.company = job.company
            existing.description = job.description
            existing.location = job.location
            existing.workplace_type = job.workplace_type.value if hasattr(job.workplace_type, "value") else str(job.workplace_type)
            return existing

        db_job = JobModel(
            id=job.id,
            title=job.title,
            company=job.company,
            company_id=job.company_id,
            description=job.description,
            location=job.location,
            country=job.country,
            city=job.city,
            workplace_type=job.workplace_type.value if hasattr(job.workplace_type, "value") else str(job.workplace_type),
            remote_scope=job.remote_scope.value if hasattr(job.remote_scope, "value") else str(job.remote_scope),
            employment_type=job.employment_type,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            salary_currency=job.salary_currency,
            experience_required=job.experience_required,
            required_skills=job.required_skills,
            preferred_skills=job.preferred_skills,
            visa_sponsorship=job.visa_sponsorship.model_dump() if hasattr(job.visa_sponsorship, "model_dump") else job.visa_sponsorship,
            relocation=job.relocation,
            application_url=job.application_url,
            source=job.source,
            source_job_id=job.source_job_id,
            posted_at=job.posted_at,
            scraped_at=job.scraped_at,
        )
        self.session.add(db_job)
        await self.session.commit()
        await self.session.refresh(db_job)
        return db_job

    async def get_by_id(self, job_id: str) -> Optional[JobModel]:
        stmt = select(JobModel).where(JobModel.id == job_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_jobs(self, limit: int = 50) -> List[JobModel]:
        stmt = select(JobModel).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
