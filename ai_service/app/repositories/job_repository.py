from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.models.application import ApplicationModel
from ai_service.app.models.job import JobModel
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.schemas.match import JobWithMatch, MatchResult


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_many(self, items: list[JobWithMatch], *, checked: bool = False) -> None:
        """Insert or update jobs. `checked`: verified jobs were just confirmed open with their board."""
        if not items:
            return
        ids = [item.job.id for item in items]
        existing = {
            row.id: row for row in (await self.session.scalars(select(JobModel).where(JobModel.id.in_(ids)))).all()
        }
        now = datetime.now(UTC)
        for item in items:
            values = _to_columns(item)
            if checked and item.job.verified:
                values["last_checked_at"] = now
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

    async def list_all(
        self,
        limit: int = 200,
        include_closed: bool = False,
        blocked_companies: list[str] | None = None,
        hidden: bool = False,
    ) -> list[JobWithMatch]:
        """Best matches first (unscored last), then most recently seen.

        Hidden jobs and companies you blocked are left out; `hidden=True` lists only the hidden jobs.
        """
        stmt = select(JobModel).order_by(
            JobModel.overall_match.is_(None), JobModel.overall_match.desc(), JobModel.updated_at.desc()
        )
        stmt = stmt.where(JobModel.hidden_at.is_not(None) if hidden else JobModel.hidden_at.is_(None))
        if not include_closed:
            stmt = stmt.where(JobModel.closed_at.is_(None))
        blocked = [c.strip().lower() for c in blocked_companies or [] if c.strip()]
        if blocked and not hidden:
            stmt = stmt.where(func.lower(JobModel.company).not_in(blocked))
        return [to_schema(row) for row in (await self.session.scalars(stmt.limit(limit))).all()]

    async def set_hidden(self, job_id: str, hidden: bool) -> bool:
        row = await self.session.get(JobModel, job_id)
        if row is None:
            return False
        row.hidden_at = datetime.now(UTC) if hidden else None
        await self.session.commit()
        return True

    async def unannounced_ids(self, ids: list[str]) -> set[str]:
        """Of `ids`, the stored jobs no alert was sent for yet (hidden and closed jobs excluded)."""
        if not ids:
            return set()
        stmt = select(JobModel.id).where(
            JobModel.id.in_(ids),
            JobModel.notified_at.is_(None),
            JobModel.hidden_at.is_(None),
            JobModel.closed_at.is_(None),
        )
        return set((await self.session.scalars(stmt)).all())

    async def mark_announced(self, ids: set[str]) -> None:
        if not ids:
            return
        await self.session.execute(update(JobModel).where(JobModel.id.in_(ids)).values(notified_at=datetime.now(UTC)))
        await self.session.commit()

    async def hidden_ids(self, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        stmt = select(JobModel.id).where(JobModel.id.in_(ids), JobModel.hidden_at.is_not(None))
        return set((await self.session.scalars(stmt)).all())

    async def iter_batches(self, size: int = 200) -> AsyncIterator[list[JobWithMatch]]:
        """Every stored job, in batches, so large stores are never loaded at once."""
        offset = 0
        while True:
            stmt = select(JobModel).order_by(JobModel.id).offset(offset).limit(size)
            rows = (await self.session.scalars(stmt)).all()
            if not rows:
                return
            yield [to_schema(row) for row in rows]
            offset += size

    async def clear(self) -> tuple[int, int]:
        """Delete stored jobs, keeping those an application refers to. Returns (deleted, kept)."""
        referenced = select(ApplicationModel.job_id)
        deleted = await self.session.execute(delete(JobModel).where(JobModel.id.not_in(referenced)))
        await self.session.commit()
        kept = await self.session.scalar(select(func.count()).select_from(JobModel))
        return deleted.rowcount or 0, kept or 0


def _to_columns(item: JobWithMatch) -> dict:
    data = item.job.model_dump(mode="python", exclude={"scraped_at", "first_seen_at", "auto_apply_supported"})
    data["visa_sponsorship"] = item.job.visa_sponsorship.model_dump(mode="json")
    data["workplace_type"] = item.job.workplace_type.value
    data["remote_scope"] = item.job.remote_scope.value
    data["match"] = item.match.model_dump(mode="json") if item.match else None
    data["overall_match"] = item.match.overall_match if item.match else None
    return data


_NOT_IN_SCHEMA = {"match", "overall_match", "last_checked_at", "hidden_at", "notified_at"}


def to_schema(row: JobModel) -> JobWithMatch:
    job = NormalizedJob.model_validate(
        {c.name: getattr(row, c.name) for c in JobModel.__table__.columns if c.name not in _NOT_IN_SCHEMA}
        | {"scraped_at": row.updated_at, "first_seen_at": row.created_at}
    )
    return JobWithMatch(job=job, match=MatchResult.model_validate(row.match) if row.match else None)
