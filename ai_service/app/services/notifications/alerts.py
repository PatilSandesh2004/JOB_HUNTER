"""Strong-match alerts: each job is announced once, on every configured channel (webhook, email)."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.match import JobWithMatch
from ai_service.app.services.notifications.email_service import EmailService
from ai_service.app.services.notifications.webhook_service import WebhookNotificationService

logger = logging.getLogger("jobpilot.alerts")

WEBHOOK_LIMIT = 5  # messages per run; the rest wait for the next run
EMAIL_LIMIT = 10


class MatchAlertService:
    def __init__(
        self,
        threshold: float,
        webhook: WebhookNotificationService | None = None,
        email: EmailService | None = None,
    ) -> None:
        self.threshold = threshold
        self.webhook = webhook
        self.email = email

    @property
    def configured(self) -> bool:
        return bool((self.webhook and self.webhook.configured) or (self.email and self.email.configured))

    def strong(self, item: JobWithMatch) -> bool:
        match = item.match
        return bool(match and match.passed_hard_filters and match.overall_match >= self.threshold)

    async def notify_new(self, session: AsyncSession, items: list[JobWithMatch]) -> int:
        """Announce strong matches not announced before (and not hidden). Returns how many were announced.

        Jobs must already be stored. A job is marked announced only when a channel delivered it, so a failed
        webhook is retried on the next search.
        """
        if not self.configured:
            return 0
        hits = sorted((i for i in items if self.strong(i)), key=lambda i: i.match.overall_match, reverse=True)
        if not hits:
            return 0
        repo = JobRepository(session)
        fresh_ids = await repo.unannounced_ids([i.job.id for i in hits])
        fresh = [i for i in hits if i.job.id in fresh_ids]
        if not fresh:
            return 0
        delivered: set[str] = set()
        if self.webhook and self.webhook.configured:
            delivered |= await self.webhook.send(fresh[:WEBHOOK_LIMIT])
        if self.email and self.email.configured:
            batch = fresh[:EMAIL_LIMIT]
            if await self.email.send_matches(batch):
                delivered |= {i.job.id for i in batch}
        await repo.mark_announced(delivered)
        if delivered:
            logger.info("Announced %d new strong match(es)", len(delivered))
        return len(delivered)
