"""Run a search from the profile's preferred roles and locations, store the results, alert on strong matches,
and (Full Auto-Pilot, if you turned it on) apply to the safest strong matches.

Used by the scheduler inside the AI service (DISCOVERY_INTERVAL_HOURS) and by workers/job_worker.py.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.app.agents.search_agent.graph import SearchAgent
from ai_service.app.core.config import Settings, settings
from ai_service.app.core.timeline import timeline_event
from ai_service.app.repositories.application_repository import ApplicationRepository
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.application import ApplicationCreate, ApplyMode
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.match import JobWithMatch
from ai_service.app.schemas.search import SearchQueryRequest
from ai_service.app.services.matching.feedback import FeedbackModel
from ai_service.app.services.notifications.alerts import MatchAlertService

logger = logging.getLogger("jobpilot.discovery")

AUTO_APPLY_MIN_TITLE_MATCH = 80.0  # the title must clearly be one of your target roles


def auto_apply_candidates(results: list[JobWithMatch], threshold: float) -> list[JobWithMatch]:
    """Jobs safe enough to apply to without review: strong overall and title match, confirmed open on the
    company's own job board, and fillable by the browser agent. Best first."""
    safe = [
        r
        for r in results
        if r.match
        and r.match.passed_hard_filters
        and r.match.overall_match >= threshold
        and r.match.title_match >= AUTO_APPLY_MIN_TITLE_MATCH
        and r.job.verified
        and r.job.auto_apply_supported
    ]
    return sorted(safe, key=lambda r: r.match.overall_match, reverse=True)


class DiscoveryService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        agent_factory: Callable[[], SearchAgent],
        notifier: MatchAlertService,
        application_service=None,
        config: Settings = settings,
    ) -> None:
        self.session_factory = session_factory
        self.agent_factory = agent_factory
        self.notifier = notifier
        self.application_service = application_service
        self.config = config

    async def run_once(
        self, roles: list[str] | None = None, locations: list[str] | None = None, remote_only: bool = False
    ) -> int:
        """Returns the number of jobs stored (0 when the profile has no roles to search for)."""
        async with self.session_factory() as session:
            candidate = await CandidateRepository(session).get_active()
            prefs = candidate.preferences if candidate else None
            if not roles and prefs:
                roles = prefs.preferred_roles or ([candidate.current_role] if candidate.current_role else [])
            if not roles:
                logger.info("Discovery skipped: no roles given and the profile has no target roles")
                return 0
            request = SearchQueryRequest(
                roles=roles,
                locations=locations or (prefs.preferred_locations if prefs else []),
                remote_only=remote_only,
                sponsorship_required=bool(prefs and prefs.visa_sponsorship_required),
            )
            response = await self.agent_factory().run(request, candidate, await FeedbackModel.load(session))
            repo = JobRepository(session)
            await repo.upsert_many(response.results, checked=True)
            hidden = await repo.hidden_ids([r.job.id for r in response.results])
            visible = [r for r in response.results if r.job.id not in hidden]
            sent = await self.notifier.notify_new(session, visible)
            queued = await self._auto_apply(session, candidate, visible)

        logger.info(
            "Discovery: %d raw -> %d jobs stored, %d alerts sent, %d auto-applications, %d source errors",
            response.total_raw,
            response.total_results,
            sent,
            queued,
            len(response.errors),
        )
        return response.total_results

    async def _auto_apply(self, session: AsyncSession, candidate: CandidateProfile | None, results) -> int:
        """Full Auto-Pilot: queue automatic applications, at most AUTO_APPLY_DAILY_LIMIT per 24 hours."""
        if candidate is None or not candidate.preferences.auto_apply_high_matches or self.application_service is None:
            return 0
        apps = ApplicationRepository(session)
        used = await apps.count_created_since(datetime.now(UTC) - timedelta(hours=24), mode=ApplyMode.AUTO.value)
        budget = self.config.auto_apply_daily_limit - used
        if budget <= 0:
            return 0
        picks = auto_apply_candidates(results, self.config.high_match_threshold)
        already = await apps.job_ids_with_applications([r.job.id for r in picks])
        queued = 0
        for item in [r for r in picks if r.job.id not in already][:budget]:
            try:
                created = await self.application_service.create(
                    session,
                    ApplicationCreate(
                        job_id=item.job.id, mode=ApplyMode.AUTO, tailor_resume=candidate.preferences.tailor_resume
                    ),
                )
            except Exception as exc:
                logger.warning("Auto-Pilot could not queue %s: %s", item.job.id, exc)
                continue
            row = await apps.get(created.id)
            if row is not None:
                why = f"{item.match.overall_match:.0f}% match; title, location and experience fit"
                await apps.update(row, events=[timeline_event("Started by Full Auto-Pilot", why)])
            queued += 1
        if queued:
            logger.info("Auto-Pilot queued %d application(s) (%d left today)", queued, budget - queued)
        return queued

    async def run_quietly(self) -> None:
        """Periodic entry point: never raises."""
        try:
            await self.run_once()
        except Exception:
            logger.exception("Scheduled discovery failed")
