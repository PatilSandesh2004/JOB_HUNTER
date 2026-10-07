"""Email alerts over SMTP (SMTP_HOST, SMTP_USER, SMTP_PASSWORD; sent to ALERT_EMAIL_TO or SMTP_USER)."""

import asyncio
import html
import logging
import smtplib
from email.message import EmailMessage

from ai_service.app.core.config import Settings, settings
from ai_service.app.schemas.match import JobWithMatch

logger = logging.getLogger("jobpilot.email")


class EmailService:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    @property
    def recipient(self) -> str:
        return self.config.alert_email_to or self.config.smtp_user

    @property
    def configured(self) -> bool:
        return bool(self.config.smtp_host and self.recipient)

    async def send_matches(self, items: list[JobWithMatch], subject: str | None = None) -> bool:
        """One email listing the jobs. Runs SMTP in a thread so the server keeps responding."""
        if not self.configured or not items:
            return False
        subject = subject or f"JobPilot: {len(items)} new match{'es' if len(items) != 1 else ''} ({items[0].job.title})"
        return await asyncio.to_thread(self._send, subject, _matches_html(items), _matches_text(items))

    async def send(self, subject: str, html_body: str, text_body: str) -> bool:
        if not self.configured:
            return False
        return await asyncio.to_thread(self._send, subject, html_body, text_body)

    def _send(self, subject: str, html_body: str, text_body: str) -> bool:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.config.smtp_from_email
        message["To"] = self.recipient
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")
        port = self.config.smtp_port
        try:
            smtp_class = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
            with smtp_class(self.config.smtp_host, port, timeout=15) as server:
                if port != 465:
                    server.starttls()
                if self.config.smtp_user and self.config.smtp_password:
                    server.login(self.config.smtp_user, self.config.smtp_password)
                server.send_message(message)
            return True
        except (OSError, smtplib.SMTPException) as exc:
            logger.error("Could not send alert email: %s", exc)
            return False


def _score(item: JobWithMatch) -> str:
    return f"{item.match.overall_match:.0f}%" if item.match else "new"


def _matches_html(items: list[JobWithMatch]) -> str:
    rows = []
    for item in items:
        job = item.job
        e = html.escape  # titles and companies come from the open web
        rows.append(
            "<li style='margin-bottom:16px;border:1px solid #ddd;padding:10px;border-radius:6px;list-style:none'>"
            f"<h3 style='margin:0 0 6px'><a href='{e(job.application_url, quote=True)}'>{e(job.title)}</a> "
            f"at {e(job.company)}</h3>"
            f"<p style='margin:2px 0'><strong>Match:</strong> {e(_score(item))} &middot; "
            f"<strong>Location:</strong> {e(job.location)} ({e(job.workplace_type.value.title())})</p>"
            + (
                f"<p style='margin:2px 0;color:#555'>{e(item.match.reasons[0])}</p>"
                if item.match and item.match.reasons
                else ""
            )
            + "</li>"
        )
    return f"<h2>JobPilot found {len(items)} new job match(es)</h2><ul style='padding:0'>{''.join(rows)}</ul>"


def _matches_text(items: list[JobWithMatch]) -> str:
    return "\n\n".join(
        f"{_score(i)}  {i.job.title} at {i.job.company} ({i.job.location})\n{i.job.application_url}" for i in items
    )
