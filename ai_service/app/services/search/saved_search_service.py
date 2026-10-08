"""Saved searches: run a search you saved on its schedule, store what it finds, alert on strong new matches."""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.app.agents.search_agent.graph import SearchAgent
from ai_service.app.core.errors import NotFoundError
from ai_service.app.models.job import JobModel
from ai_service.app.models.saved_search import SavedSearchModel
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.search import SearchQueryRequest
from ai_service.app.services.matching.feedback import FeedbackModel
from ai_service.app.services.notifications.alerts import MatchAlertService

logger = logging.getLogger("jobpilot.saved_searches")


def as_dict(row: SavedSearchModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "request": row.request,
        "interval_hours": row.interval_hours,
        "enabled": row.enabled,
        "last_run_at": row.last_run_at,
        "last_found": row.last_found,
        "last_new": row.last_new,
        "last_error": row.last_error,
        "created_at": row.created_at,
    }


class SavedSearchService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        agent_factory: Callable[[], SearchAgent],
        notifier: MatchAlertService,
    ) -> None:
        self.session_factory = session_factory
        self.agent_factory = agent_factory
        self.notifier = notifier

    async def create(self, session: AsyncSession, name: str, request: SearchQueryRequest, interval_hours: float):
        row = SavedSearchModel(
            id=str(uuid.uuid4()),
            name=name.strip() or ", ".join(request.roles) or "My search",
            request=request.model_dump(mode="json"),
            interval_hours=interval_hours,
            enabled=True,
            last_found=0,
            last_new=0,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def run(self, search_id: str) -> SavedSearchModel:
        """Run one saved search now; returns it with last_found/last_new updated."""
        async with self.session_factory() as session:
            row = await session.get(SavedSearchModel, search_id)
            if row is None:
                raise NotFoundError("Saved search not found")
            candidate = await CandidateRepository(session).get_active()
            try:
                request = SearchQueryRequest.model_validate(row.request)
                response = await self.agent_factory().run(request, candidate, await FeedbackModel.load(session))
                ids = [r.job.id for r in response.results]
                known = set((await session.scalars(select(JobModel.id).where(JobModel.id.in_(ids)))).all())
                repo = JobRepository(session)
                await repo.upsert_many(response.results, checked=True)
                hidden = await repo.hidden_ids(ids)
                await self.notifier.notify_new(session, [r for r in response.results if r.job.id not in hidden])
                row.last_found, row.last_new, row.last_error = len(ids), len(set(ids) - known), None
            except Exception as exc:  # a bad search or an outage: record it and keep the schedule
                logger.warning("Saved search %s failed: %s", row.name, exc)
                row.last_error = str(exc)[:500]
            row.last_run_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return row

    async def run_due(self) -> int:
        """Periodic entry point: run every enabled search whose interval has passed. Never raises."""
        now = datetime.now(UTC)
        try:
            async with self.session_factory() as session:
                rows = (await session.scalars(select(SavedSearchModel).where(SavedSearchModel.enabled.is_(True)))).all()
                due = [
                    r.id
                    for r in rows
                    if r.interval_hours > 0
                    and (r.last_run_at is None or now - _aware(r.last_run_at) >= timedelta(hours=r.interval_hours))
                ]
        except Exception:
            logger.exception("Could not read saved searches")
            return 0
        for search_id in due:
            await self.run(search_id)
        return len(due)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
