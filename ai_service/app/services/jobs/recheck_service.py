"""Re-verify stored jobs with their job board and mark postings that have closed."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.app.core.config import settings
from ai_service.app.models.job import JobModel
from ai_service.app.services.jobs.enrichment_service import JobEnrichmentService

logger = logging.getLogger("jobpilot.recheck")

# ATSs whose public API tells us whether a posting still exists (see JobEnrichmentService).
VERIFIABLE_ATS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters")


class JobRecheckService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], enricher: JobEnrichmentService) -> None:
        self.session_factory = session_factory
        self.enricher = enricher

    async def recheck_stale(self, limit: int, min_age_hours: float | None = None) -> dict[str, int]:
        """Check up to `limit` open jobs not checked for `min_age_hours` (oldest first)."""
        age = settings.job_recheck_interval_hours if min_age_hours is None else min_age_hours
        cutoff = datetime.now(UTC) - timedelta(hours=age)
        async with self.session_factory() as session:
            stmt = (
                select(JobModel)
                .where(
                    JobModel.closed_at.is_(None),
                    JobModel.ats.in_(VERIFIABLE_ATS),
                    (JobModel.last_checked_at.is_(None)) | (JobModel.last_checked_at < cutoff),
                )
                .order_by(JobModel.last_checked_at.is_not(None), JobModel.last_checked_at)
                .limit(limit)
            )
            rows = list((await session.scalars(stmt)).all())
            if not rows:
                return {"checked": 0, "closed": 0, "unknown": 0}
            states = await self.enricher.check_open([row.application_url for row in rows])
            now = datetime.now(UTC)
            closed = unknown = 0
            for row, is_open in zip(rows, states, strict=True):
                row.last_checked_at = now
                if is_open is False:
                    row.closed_at = now
                    closed += 1
                elif is_open is None:
                    unknown += 1
            await session.commit()
        if closed:
            logger.info("Job re-check: %d of %d postings have closed", closed, len(rows))
        return {"checked": len(rows), "closed": closed, "unknown": unknown}
