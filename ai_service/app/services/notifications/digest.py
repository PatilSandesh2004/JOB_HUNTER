"""Scheduled emails: a digest of new strong matches every ALERT_DIGEST_HOURS, and a weekly progress report.

When each was last sent is kept in data/digests.json, so they go out on schedule even if the service restarts
often. Both need SMTP settings; without them nothing is sent.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.app.core.config import Settings, settings
from ai_service.app.models.job import JobModel
from ai_service.app.repositories.job_repository import to_schema
from ai_service.app.services.applications.report_service import progress_report, report_email
from ai_service.app.services.notifications.email_service import EmailService

logger = logging.getLogger("jobpilot.digest")

DIGEST_SIZE = 15
DIGEST_MARGIN = 10.0  # the digest includes good matches a little below the instant-alert threshold


class DigestService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        email: EmailService,
        config: Settings = settings,
        state_path: Path | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.email = email
        self.config = config
        self.state_path = state_path or config.data_dir / "digests.json"

    def _state(self) -> dict[str, str]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _due(self, name: str, every: timedelta, now: datetime) -> bool:
        last = self._state().get(name)
        if last is None:
            self._mark(name, now)  # the first period starts now
            return False
        return now - datetime.fromisoformat(last) >= every

    def _mark(self, name: str, now: datetime) -> None:
        state = self._state() | {name: now.isoformat()}
        try:
            self.state_path.write_text(json.dumps(state), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not save digest state: %s", exc)

    async def run_due(self) -> None:
        """Periodic entry point (checked hourly): send whichever emails are due. Never raises."""
        if not self.email.configured:
            return
        now = datetime.now(UTC)
        try:
            hours = self.config.alert_digest_hours
            if hours > 0 and self._due("matches", timedelta(hours=hours), now):
                await self.send_match_digest(timedelta(hours=hours))
                self._mark("matches", now)
            if self.config.weekly_report_email and self._due("weekly", timedelta(days=7), now):
                await self.send_weekly_report()
                self._mark("weekly", now)
        except Exception:
            logger.exception("Scheduled email failed")

    async def send_match_digest(self, window: timedelta) -> int:
        since = datetime.now(UTC) - window
        floor = self.config.high_match_threshold - DIGEST_MARGIN
        async with self.session_factory() as session:
            stmt = (
                select(JobModel)
                .where(
                    JobModel.created_at >= since,
                    JobModel.hidden_at.is_(None),
                    JobModel.closed_at.is_(None),
                    JobModel.overall_match >= floor,
                )
                .order_by(JobModel.overall_match.desc())
                .limit(DIGEST_SIZE * 2)
            )
            items = [to_schema(row) for row in (await session.scalars(stmt)).all()]
        items = [i for i in items if i.match and i.match.passed_hard_filters][:DIGEST_SIZE]
        if not items:
            return 0
        subject = f"JobPilot digest: {len(items)} new match{'es' if len(items) != 1 else ''}"
        return len(items) if await self.email.send_matches(items, subject) else 0

    async def send_weekly_report(self) -> bool:
        async with self.session_factory() as session:
            report = await progress_report(session, days=7)
        return await self.email.send(*report_email(report))
