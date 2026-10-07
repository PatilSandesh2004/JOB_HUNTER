import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.core.config import settings
from ai_service.app.models.application import ApplicationModel
from ai_service.app.schemas.application import ApplicationRead, ApplicationStatus

MAX_EVENTS = 200


class ApplicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> ApplicationModel:
        row = ApplicationModel(id=str(uuid.uuid4()), **values)
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def get(self, application_id: str) -> ApplicationModel | None:
        return await self.session.get(ApplicationModel, application_id)

    async def update(
        self, row: ApplicationModel, *, events: list[dict[str, Any]] | None = None, **values: Any
    ) -> ApplicationModel:
        """Set columns; `events` are appended to the activity timeline (capped at MAX_EVENTS)."""
        for key, value in values.items():
            setattr(row, key, value)
        if events:
            # Assign a new list: in-place mutation of a JSON column is not detected by SQLAlchemy.
            row.events = [*(row.events or []), *events][-MAX_EVENTS:]
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_all(self, statuses: Iterable[ApplicationStatus] | None = None) -> list[ApplicationModel]:
        stmt = select(ApplicationModel).order_by(ApplicationModel.created_at.desc())
        if statuses:
            stmt = stmt.where(ApplicationModel.status.in_([s.value for s in statuses]))
        return list((await self.session.scalars(stmt)).all())

    async def job_ids_with_applications(self, job_ids: list[str]) -> set[str]:
        """Of `job_ids`, those you have any application for (including dismissed or failed ones)."""
        if not job_ids:
            return set()
        stmt = select(ApplicationModel.job_id).where(ApplicationModel.job_id.in_(job_ids))
        return set((await self.session.scalars(stmt)).all())

    async def count_created_since(self, since: datetime, mode: str | None = None) -> int:
        stmt = select(func.count()).select_from(ApplicationModel).where(ApplicationModel.created_at >= since)
        if mode is not None:
            stmt = stmt.where(ApplicationModel.mode == mode)
        return await self.session.scalar(stmt) or 0

    async def find_open_for_job(self, job_id: str) -> ApplicationModel | None:
        closed = [ApplicationStatus.DISMISSED.value, ApplicationStatus.FAILED.value]
        stmt = select(ApplicationModel).where(ApplicationModel.job_id == job_id, ApplicationModel.status.not_in(closed))
        return (await self.session.scalars(stmt)).first()


def follow_up_due(row: ApplicationModel, now: datetime | None = None) -> bool:
    """Applied, and nothing has happened for FOLLOW_UP_DAYS: a polite nudge to the company is due."""
    if settings.follow_up_days <= 0 or row.status != ApplicationStatus.APPLIED.value:
        return False
    last = max(d for d in (row.updated_at, row.applied_at) if d is not None)
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - last >= timedelta(days=settings.follow_up_days)


def to_schema(row: ApplicationModel) -> ApplicationRead:
    read = ApplicationRead.model_validate(row)
    read.has_screenshot = bool(row.screenshot_path)
    read.has_tailored_resume = bool(row.tailored_resume_path)
    read.follow_up_due = follow_up_due(row)
    return read
