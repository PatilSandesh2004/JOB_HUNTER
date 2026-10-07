"""High-match job alerts to a Slack/Discord-compatible incoming webhook."""

import asyncio
import logging

import httpx

from ai_service.app.core.http import tls_verify
from ai_service.app.schemas.match import JobWithMatch

logger = logging.getLogger("jobpilot.webhook")


class WebhookNotificationService:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    @property
    def configured(self) -> bool:
        return bool(self.webhook_url)

    async def send(self, items: list[JobWithMatch]) -> set[str]:
        """Post one message per job. Returns the ids of the jobs that were delivered."""
        if not self.webhook_url or not items:
            return set()
        async with httpx.AsyncClient(timeout=5.0, verify=tls_verify()) as client:
            delivered = await asyncio.gather(*(self._send(client, i) for i in items))
        return {item.job.id for item, ok in zip(items, delivered, strict=True) if ok}

    async def _send(self, client: httpx.AsyncClient, item: JobWithMatch) -> bool:
        job, match = item.job, item.match
        score = f"{match.overall_match:.0f}%" if match else "new"
        text = (
            f"JobPilot match {score}: *{job.title}* at *{job.company}*\n"
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
