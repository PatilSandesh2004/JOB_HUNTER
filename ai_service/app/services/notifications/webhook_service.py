import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger("jobpilot.webhook")


class WebhookNotificationService:
    """
    Sends instant Slack/Telegram/Discord notification webhooks
    when high-fit jobs (>85% Match) or Visa Sponsorship postings are discovered.
    """

    async def send_job_alert(
        self,
        webhook_url: str,
        job_title: str,
        company: str,
        match_score: float,
        visa_status: str,
        application_url: str
    ) -> bool:
        if not webhook_url:
            return False

        payload = {
            "text": f"🚀 *JobPilot High Match Alert!*\n"
                    f"*Role:* {job_title}\n"
                    f"*Company:* {company}\n"
                    f"*Fit Score:* {match_score}%\n"
                    f"*Visa Sponsored:* {visa_status}\n"
                    f"*Apply Link:* {application_url}"
        }

        try:
            async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
                res = await client.post(webhook_url, json=payload)
                return res.status_code in [200, 201, 204]
        except Exception as e:
            logger.warning(f"Webhook alert delivery failed: {e}")
            return False
