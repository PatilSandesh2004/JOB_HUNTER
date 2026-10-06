from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.models.job import JobModel
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.schemas.match import JobWithMatch, MatchResult


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_many(self, items: list[JobWithMatch]) -> None:
        if not items:
            return
        ids = [item.job.id for item in items]
        existing = {
            row.id: row for row in (await self.session.scalars(select(JobModel).where(JobModel.id.in_(ids)))).all()
        }
        for item in items:
            values = _to_columns(item)
            row = existing.get(item.job.id)
            if row is None:
                self.session.add(JobModel(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        await self.session.commit()

    async def get(self, job_id: str) -> NormalizedJob | None:
        row = await self.session.get(JobModel, job_id)
        return to_schema(row).job if row else None

    async def list_all(self, limit: int = 200) -> list[JobWithMatch]:
        rows = (await self.session.scalars(select(JobModel).order_by(JobModel.updated_at.desc()).limit(limit))).all()
        items = [to_schema(row) for row in rows]
        return sorted(items, key=lambda i: i.match.overall_match if i.match else -1, reverse=True)

    async def clear(self) -> int:
        rows = (await self.session.scalars(select(JobModel))).all()
        for row in rows:
            await self.session.delete(row)
        await self.session.commit()
        return len(rows)


def _to_columns(item: JobWithMatch) -> dict:
    data = item.job.model_dump(mode="python", exclude={"scraped_at", "auto_apply_supported"})
    data["visa_sponsorship"] = item.job.visa_sponsorship.model_dump(mode="json")
    data["workplace_type"] = item.job.workplace_type.value
    data["remote_scope"] = item.job.remote_scope.value
    data["match"] = item.match.model_dump(mode="json") if item.match else None
    return data


def to_schema(row: JobModel) -> JobWithMatch:
    job = NormalizedJob.model_validate(
        {c.name: getattr(row, c.name) for c in JobModel.__table__.columns if c.name != "match"}
        | {"scraped_at": row.updated_at}
    )
    return JobWithMatch(job=job, match=MatchResult.model_validate(row.match) if row.match else None)
