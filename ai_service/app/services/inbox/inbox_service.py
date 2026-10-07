"""Read the user's inbox: add jobs from LinkedIn / Indeed / Naukri job alerts, and move applications forward
from employer replies ("we received your application", interview invitations, rejections).

Each email is processed once (see InboxMessageModel). Only job alerts and emails naming a company you
applied to are downloaded; nothing about other emails is stored.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.app.core.config import Settings, settings
from ai_service.app.core.errors import JobPilotError
from ai_service.app.core.timeline import timeline_event
from ai_service.app.integrations.mail.imap_reader import MailError, MailMessage, WantFn
from ai_service.app.models.application import ApplicationModel
from ai_service.app.models.inbox_message import InboxMessageModel
from ai_service.app.models.job import JobModel
from ai_service.app.repositories.application_repository import ApplicationRepository
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.application import ApplicationStatus
from ai_service.app.schemas.match import JobWithMatch
from ai_service.app.schemas.search import RawJobPosting
from ai_service.app.services.inbox.classifier import classify_email
from ai_service.app.services.inbox.job_alerts import SOURCE_LABEL, alert_source, parse_job_alert
from ai_service.app.services.inbox.status_updates import TRACKED, match_application, names_company, next_status
from ai_service.app.services.jobs.deduplication_service import JobDeduplicationService
from ai_service.app.services.jobs.normalization_service import JobNormalizationService
from ai_service.app.services.matching.matching_engine import MatchingEngineService
from ai_service.app.services.notifications.webhook_service import WebhookNotificationService
from ai_service.app.services.search.search_service import strip_html

logger = logging.getLogger("jobpilot.inbox")


class InboxNotConfiguredError(JobPilotError):
    pass


class MailReader(Protocol):
    async def fetch(self, since_days: int, limit: int, want: WantFn) -> list[MailMessage]: ...


class InboxService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reader: MailReader | None,
        notifier: WebhookNotificationService | None = None,
        config: Settings = settings,
        transport: httpx.AsyncBaseTransport | None = None,
        llm = None,
    ) -> None:
        self.session_factory = session_factory
        self.reader = reader
        self.notifier = notifier
        self.config = config
        self.transport = transport  # injectable for tests (tracking-link resolution)
        self.llm = llm
        self.last_report: dict[str, Any] | None = None

    @property
    def configured(self) -> bool:
        return self.reader is not None

    async def status(self) -> dict[str, Any]:
        async with self.session_factory() as session:
            stmt = (
                select(InboxMessageModel)
                .where(InboxMessageModel.kind.in_(("job_alert", "status_update")))
                .order_by(InboxMessageModel.created_at.desc())
                .limit(15)
            )
            recent = (await session.scalars(stmt)).all()
        return {
            "configured": self.configured,
            "account": self.config.imap_user or None,
            "interval_minutes": self.config.inbox_check_interval_minutes,
            "last_check": self.last_report,
            "recent": [
                {"kind": r.kind, "sender": r.sender, "subject": r.subject, "received_at": r.received_at, **r.detail}
                for r in recent
            ],
        }

    async def check_if_configured(self) -> None:
        """Periodic entry point: never raises."""
        if not self.configured:
            return
        try:
            await self.check()
        except Exception:
            logger.exception("Inbox check failed")

    async def check(self) -> dict[str, Any]:
        if self.reader is None:
            raise InboxNotConfiguredError(
                "Inbox not set up: add IMAP_USER and IMAP_PASSWORD (a Gmail app password) to .env and restart"
            )
        report: dict[str, Any] = {
            "checked_at": datetime.now(UTC).isoformat(),
            "messages": 0,
            "job_alerts": 0,
            "jobs_found": 0,
            "jobs_new": 0,
            "status_updates": [],
            "errors": [],
        }
        async with self.session_factory() as session:
            known = set((await session.scalars(select(InboxMessageModel.id))).all())
            apps = list(
                (
                    await session.scalars(
                        select(ApplicationModel).where(ApplicationModel.status.in_([s.value for s in TRACKED]))
                    )
                ).all()
            )
            candidate = await CandidateRepository(session).get_active()

            def want(key: str, sender: str, subject: str) -> bool:
                if key in known:
                    return False
                if alert_source(sender):
                    return True
                return self.config.inbox_update_statuses and any(
                    names_company(a.company, sender, subject) for a in apps
                )

            try:
                messages = await self.reader.fetch(
                    self.config.inbox_lookback_days, self.config.inbox_max_messages, want
                )
            except MailError as exc:
                report["errors"].append(str(exc))
                self.last_report = report
                return report
            report["messages"] = len(messages)

            postings: list[RawJobPosting] = []
            async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
                resolver = client if self.config.inbox_resolve_tracking_links else None
                for message in messages:
                    if message.key in known:
                        continue
                    known.add(message.key)
                    source = alert_source(message.sender)
                    if source:
                        found = await self._alert_postings(source, message, resolver)
                        postings += found
                        report["job_alerts"] += 1
                        session.add(_record(message, "job_alert", {"source": source, "jobs": len(found)}))
                        continue
                    update = await self._status_update(session, message, apps, candidate)
                    if update:
                        report["status_updates"].append(update)
                    session.add(
                        _record(message, "status_update", update) if update else _record(message, "no_update", {})
                    )
            await session.commit()
            report["jobs_found"], report["jobs_new"] = await self._store(session, postings, candidate)

        self.last_report = report
        logger.info(
            "Inbox: %d emails, %d alerts, %d new jobs, %d status updates",
            report["messages"],
            report["job_alerts"],
            report["jobs_new"],
            len(report["status_updates"]),
        )
        return report

    async def _alert_postings(
        self, source: str, message: MailMessage, resolver: httpx.AsyncClient | None
    ) -> list[RawJobPosting]:
        jobs = await parse_job_alert(source, message.html, message.text, resolver)
        label = SOURCE_LABEL[source]
        return [
            RawJobPosting(
                title=job.title,
                url=job.url,
                company=job.company,
                location=job.location,
                snippet=f"From your {label} job alert: {message.subject}",
                source=f"email_{source}",
                posted_at=message.received_at,
            )
            for job in jobs
        ]

    async def _status_update(
        self, session: AsyncSession, message: MailMessage, apps: list[ApplicationModel], candidate
    ) -> dict[str, Any] | None:
        app = match_application(apps, message.sender, message.subject)
        if app is None:
            return None
        classified = classify_email(message.subject, message.text or strip_html(message.html, 20_000))
        created = app.created_at if app.created_at.tzinfo else app.created_at.replace(tzinfo=UTC)
        if message.received_at and message.received_at < created - timedelta(days=1):
            return None  # an older email, from before this application
        current = ApplicationStatus(app.status)
        new = next_status(current, classified.status)
        if new is None:
            return None
            
        sender = message.sender.split("<")[0].strip(' "') or message.sender
        events = [timeline_event(f"Email: {new.value.replace('_', ' ').title()}", f"{sender}: {message.subject}")]
        
        if new == ApplicationStatus.INTERVIEW and self.llm:
            try:
                system_prompt = "You draft polite, professional replies to recruiters for interview requests. Keep it very concise (3-4 sentences max). Use placeholders like [Insert Date/Time] for availability. Return only the email body."
                user_prompt = f"Draft a reply to this email from {app.company} scheduling an interview.\nCandidate Name: {candidate.name}\nRecruiter Email:\nSubject: {message.subject}\n\n{message.text[:1000]}"
                draft = await self.llm.complete(system_prompt, user_prompt)
                if draft:
                    events.append(timeline_event("Drafted Interview Reply", f"Copy and use this draft:\n\n{draft.strip()}"))
            except Exception as e:
                logger.warning(f"Failed to draft reply: {e}")

        changes: dict[str, Any] = {"status": new.value}
        if new == ApplicationStatus.APPLIED and app.applied_at is None:
            changes["applied_at"] = message.received_at or datetime.now(UTC)
        await ApplicationRepository(session).update(
            app,
            events=events,
            **changes,
        )
        return {
            "application_id": app.id,
            "company": app.company,
            "job_title": app.job_title,
            "from": current.value,
            "to": new.value,
            "phrase": classified.matched_phrase,
        }

    async def _store(self, session: AsyncSession, postings: list[RawJobPosting], candidate) -> tuple[int, int]:
        """Score and save jobs that are not stored yet (an alert never overwrites richer search data)."""
        if not postings:
            return 0, 0
        normalizer = JobNormalizationService()
        jobs = JobDeduplicationService().deduplicate([normalizer.normalize(p) for p in postings])
        blocked = {c.strip().lower() for c in (candidate.preferences.blocked_companies if candidate else [])}
        jobs = [j for j in jobs if j.company.strip().lower() not in blocked]
        stmt = select(JobModel.id).where(JobModel.id.in_([j.id for j in jobs]))
        existing = set((await session.scalars(stmt)).all())
        matcher = MatchingEngineService()
        new = [
            JobWithMatch(job=j, match=matcher.evaluate_match(candidate, j) if candidate else None)
            for j in jobs
            if j.id not in existing
        ]
        await JobRepository(session).upsert_many(new)
        if self.notifier is not None and new:
            await self.notifier.notify_high_matches(new)
        return len(jobs), len(new)


def _record(message: MailMessage, kind: str, detail: dict[str, Any]) -> InboxMessageModel:
    keep = kind != "no_update"  # unrelated emails leave only their hash behind
    return InboxMessageModel(
        id=message.key,
        kind=kind,
        sender=message.sender[:320] if keep else None,
        subject=message.subject[:500] if keep else None,
        received_at=message.received_at,
        detail=detail,
    )
