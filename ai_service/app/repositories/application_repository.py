import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def find_open_for_job(self, job_id: str) -> ApplicationModel | None:
        closed = [ApplicationStatus.DISMISSED.value, ApplicationStatus.FAILED.value]
        stmt = select(ApplicationModel).where(ApplicationModel.job_id == job_id, ApplicationModel.status.not_in(closed))
        return (await self.session.scalars(stmt)).first()


def to_schema(row: ApplicationModel) -> ApplicationRead:
    read = ApplicationRead.model_validate(row)
    read.has_screenshot = bool(row.screenshot_path)
    read.has_tailored_resume = bool(row.tailored_resume_path)
    return read
