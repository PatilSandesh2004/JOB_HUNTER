"""High-match job alerts to a Slack/Discord-compatible incoming webhook."""

import asyncio
import logging

import httpx

from ai_service.app.schemas.match import JobWithMatch

logger = logging.getLogger("jobpilot.webhook")


class WebhookNotificationService:
    def __init__(self, webhook_url: str, threshold: float) -> None:
        self.webhook_url = webhook_url
        self.threshold = threshold

    async def notify_high_matches(self, items: list[JobWithMatch], limit: int = 5) -> int:
        if not self.webhook_url:
            return 0
        hits = [i for i in items if i.match and i.match.passed_hard_filters and i.match.overall_match >= self.threshold]
        async with httpx.AsyncClient(timeout=5.0) as client:
            results = await asyncio.gather(*(self._send(client, i) for i in hits[:limit]))
        return sum(results)

    async def _send(self, client: httpx.AsyncClient, item: JobWithMatch) -> bool:
        job, match = item.job, item.match
        text = (
            f"JobPilot match {match.overall_match:.0f}%: *{job.title}* at *{job.company}*\n"
            f"Location: {job.location} ({job.workplace_type.value}) | Visa: {job.visa_sponsorship.status.value}\n"
            f"{job.application_url}"
        )
        try:
            # "text" for Slack, "content" for Discord.
            response = await client.post(self.webhook_url, json={"text": text, "content": text})
            return response.is_success
        except httpx.HTTPError as exc:
            logger.warning("Webhook delivery failed: %s", exc)
            return False
