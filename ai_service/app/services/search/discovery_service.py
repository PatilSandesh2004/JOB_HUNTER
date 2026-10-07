"""Run a search from the profile's preferred roles and locations, store the results, alert on strong matches.

Used by the scheduler inside the AI service (DISCOVERY_INTERVAL_HOURS) and by workers/job_worker.py.
"""

import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.app.agents.search_agent.graph import SearchAgent
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.search import SearchQueryRequest
from ai_service.app.services.notifications.webhook_service import WebhookNotificationService
from ai_service.app.services.notifications.email_service import email_service

logger = logging.getLogger("jobpilot.discovery")


class DiscoveryService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        agent_factory: Callable[[], SearchAgent],
        notifier: WebhookNotificationService,
        application_service = None,
    ) -> None:
        self.session_factory = session_factory
        self.agent_factory = agent_factory
        self.notifier = notifier
        self.application_service = application_service

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
            response = await self.agent_factory().run(request, candidate)
            repo = JobRepository(session)
            await repo.upsert_many(response.results, checked=True)
            hidden = await repo.hidden_ids([r.job.id for r in response.results])
            sent_webhook = await self.notifier.notify_high_matches([r for r in response.results if r.job.id not in hidden])
            sent_email = email_service.notify_high_matches([r for r in response.results if r.job.id not in hidden])
            sent = max(sent_webhook, sent_email)
            
            if candidate and candidate.preferences.auto_apply_high_matches and self.application_service:
                from ai_service.app.schemas.application import ApplicationCreate, ApplyMode
                from ai_service.app.core.config import settings as app_settings
                high_matches = [r for r in response.results if r.job.id not in hidden and r.match and r.match.overall_match >= app_settings.high_match_threshold]
                queued_count = 0
                for r in high_matches[:5]:  # Safety limit per discovery run
                    if not r.job.auto_apply_supported:
                        continue
                    try:
                        await self.application_service.create(
                            session,
                            ApplicationCreate(
                                job_id=r.job.id,
                                mode=ApplyMode.AUTO,
                                tailor_resume=candidate.preferences.tailor_resume
                            )
                        )
                        queued_count += 1
                    except Exception as exc:
                        logger.warning("Auto-apply failed to queue %s: %s", r.job.id, exc)
                if queued_count > 0:
                    logger.info(f"Auto-Pilot queued {queued_count} high-match jobs for auto-apply.")

        logger.info(
            "Discovery: %d raw -> %d jobs stored, %d alerts sent, %d source errors",
            response.total_raw,
            response.total_results,
            sent,
            len(response.errors),
        )
        return response.total_results

    async def run_quietly(self) -> None:
        """Periodic entry point: never raises."""
        try:
            await self.run_once()
        except Exception:
            logger.exception("Scheduled discovery failed")
