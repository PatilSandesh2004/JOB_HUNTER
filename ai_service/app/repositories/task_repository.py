import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.models.task import TaskModel


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class TaskKind(StrEnum):
    FILL_APPLICATION = "fill_application"  # draft letter + fill the form (and submit in auto mode)
    SUBMIT_APPLICATION = "submit_application"  # after human approval
    DRAFT_COVER_LETTER = "draft_cover_letter"  # manual applications


ACTIVE = (TaskStatus.QUEUED.value, TaskStatus.RUNNING.value)


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        kind: TaskKind,
        *,
        application_id: str | None = None,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 1,
        commit: bool = True,
    ) -> TaskModel:
        task = TaskModel(
            id=str(uuid.uuid4()),
            kind=kind.value,
            application_id=application_id,
            payload=payload or {},
            status=TaskStatus.QUEUED.value,
            attempts=0,
            max_attempts=max(1, max_attempts),
            run_after=datetime.now(UTC),
        )
        self.session.add(task)
        if commit:
            await self.session.commit()
        return task

    async def due_ids(self, limit: int, exclude: set[str] | frozenset[str] = frozenset()) -> list[str]:
        stmt = (
            select(TaskModel.id)
            .where(TaskModel.status == TaskStatus.QUEUED.value, TaskModel.run_after <= datetime.now(UTC))
            .order_by(TaskModel.run_after)
            .limit(limit + len(exclude))
        )
        return [i for i in (await self.session.scalars(stmt)).all() if i not in exclude][:limit]

    async def claim(self, task_id: str) -> TaskModel | None:
        """Atomically move a queued task to running. Returns None if another worker got it first."""
        result = await self.session.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id, TaskModel.status == TaskStatus.QUEUED.value)
            .values(status=TaskStatus.RUNNING.value, attempts=TaskModel.attempts + 1, updated_at=datetime.now(UTC))
        )
        await self.session.commit()
        if result.rowcount != 1:
            return None
        return await self.session.get(TaskModel, task_id, populate_existing=True)

    async def finish(
        self, task_id: str, status: TaskStatus, error: str | None = None, retry_in: float | None = None
    ) -> None:
        values: dict[str, Any] = {"status": status.value, "last_error": error, "updated_at": datetime.now(UTC)}
        if retry_in is not None:
            values["run_after"] = datetime.now(UTC) + timedelta(seconds=retry_in)
        await self.session.execute(update(TaskModel).where(TaskModel.id == task_id).values(**values))
        await self.session.commit()

    async def list_running(self) -> list[TaskModel]:
        stmt = select(TaskModel).where(TaskModel.status == TaskStatus.RUNNING.value)
        return list((await self.session.scalars(stmt)).all())

    async def has_active(self, application_id: str) -> bool:
        stmt = select(TaskModel.id).where(TaskModel.application_id == application_id, TaskModel.status.in_(ACTIVE))
        return (await self.session.scalars(stmt.limit(1))).first() is not None
