"""Application lifecycle: create -> fill (preview) -> human approval -> submit."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.app.agents.application_agent.graph import ApplicationAgent
from ai_service.app.core.config import settings
from ai_service.app.core.errors import JobPilotError, NotFoundError
from ai_service.app.integrations.browser.form_filler import FillOutcome, FillResult
from ai_service.app.models.job import JobModel
from ai_service.app.repositories import job_repository
from ai_service.app.repositories.application_repository import ApplicationRepository, to_schema
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.candidate_repository import to_schema as candidate_to_schema
from ai_service.app.schemas.application import ApplicationCreate, ApplicationRead, ApplicationStatus, ApplyMode
from ai_service.app.services.jobs.ats import detect_ats

logger = logging.getLogger("jobpilot.applications")

APPROVABLE = {ApplicationStatus.PENDING_APPROVAL, ApplicationStatus.NEEDS_MANUAL, ApplicationStatus.FAILED}
IN_FLIGHT = {ApplicationStatus.PROCESSING, ApplicationStatus.SUBMITTING}
MANUAL_STATUSES = {
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.REJECTED,
    ApplicationStatus.DISMISSED,
}


class ApplicationConflictError(JobPilotError):
    pass


class ApplicationService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], agent_factory: Callable[[], ApplicationAgent]
    ):
        self.session_factory = session_factory
        self.agent_factory = agent_factory

    # ---- request-time operations ----------------------------------------
    async def create(self, session: AsyncSession, payload: ApplicationCreate) -> tuple[ApplicationRead, str | None]:
        """Create (or reuse) an application. Returns it plus the background task to run:
        "agent" (fill/submit form), "letter" (draft cover letter only) or None."""
        manual = payload.mode == ApplyMode.MANUAL
        candidate = await CandidateRepository(session).get_active()
        if not manual and (candidate is None or not candidate.name or not candidate.email):
            raise ApplicationConflictError("Complete your profile (at least name and email) before auto-filling")
        if candidate is None:
            raise ApplicationConflictError("Create your profile first (upload your resume on the Profile tab)")
        job_row = await session.get(JobModel, payload.job_id)
        if job_row is None:
            raise NotFoundError(f"Job {payload.job_id} not found")
        if not manual and not detect_ats(job_row.application_url).auto_apply_supported:
            raise ApplicationConflictError(
                "Auto-fill is not supported on this site (no fillable form, login or bot protection). "
                "Use 'Apply manually' instead."
            )

        repo = ApplicationRepository(session)
        existing = await repo.find_open_for_job(payload.job_id)
        if existing is not None:
            status = ApplicationStatus(existing.status)
            if manual and status in APPROVABLE:
                existing = await repo.update(
                    existing, status=ApplicationStatus.AWAITING_CONFIRMATION.value, mode=ApplyMode.MANUAL.value
                )
            elif manual and status in IN_FLIGHT:
                raise ApplicationConflictError("The agent is still working on this application; try again shortly")
            return to_schema(existing), None

        row = await repo.create(
            candidate_id=candidate.id,
            job_id=job_row.id,
            job_title=job_row.title,
            company=job_row.company,
            application_url=job_row.application_url,
            status=(ApplicationStatus.AWAITING_CONFIRMATION if manual else ApplicationStatus.PROCESSING).value,
            mode=payload.mode.value,
            cover_letter=payload.cover_letter,
            cover_letter_source="user" if payload.cover_letter else None,
        )
        task = None if payload.cover_letter and manual else ("letter" if manual else "agent")
        return to_schema(row), task

    async def approve(self, session: AsyncSession, application_id: str) -> ApplicationRead:
        repo = ApplicationRepository(session)
        row = await self._get(repo, application_id)
        if ApplicationStatus(row.status) not in APPROVABLE:
            raise ApplicationConflictError(f"Cannot submit an application in status {row.status}")
        row = await repo.update(row, status=ApplicationStatus.SUBMITTING.value, error=None)
        return to_schema(row)

    async def update(
        self, session: AsyncSession, application_id: str, cover_letter: str | None, status: ApplicationStatus | None
    ) -> ApplicationRead:
        repo = ApplicationRepository(session)
        row = await self._get(repo, application_id)
        if ApplicationStatus(row.status) in IN_FLIGHT:
            raise ApplicationConflictError("The agent is still working on this application")
        changes: dict = {}
        if cover_letter is not None:
            changes |= {"cover_letter": cover_letter, "cover_letter_source": "user"}
        if status is not None:
            if status not in MANUAL_STATUSES:
                raise ApplicationConflictError(f"Status {status} cannot be set manually")
            changes["status"] = status.value
            if status == ApplicationStatus.APPLIED and row.applied_at is None:
                changes["applied_at"] = datetime.now(UTC)
        return to_schema(await repo.update(row, **changes))

    @staticmethod
    async def _get(repo: ApplicationRepository, application_id: str):
        row = await repo.get(application_id)
        if row is None:
            raise NotFoundError(f"Application {application_id} not found")
        return row

    # ---- background work -------------------------------------------------
    async def process(self, application_id: str, submit: bool) -> None:
        """Run the agent for an application. Executed as a background task with its own session."""
        async with self.session_factory() as session:
            repo = ApplicationRepository(session)
            row = await repo.get(application_id)
            if row is None:
                return
            try:
                candidate_row = await CandidateRepository(session).get_model(row.candidate_id)
                job_row = await session.get(JobModel, row.job_id)
                if candidate_row is None or job_row is None:
                    raise NotFoundError("Candidate or job no longer exists")
                job_with_match = job_repository.to_schema(job_row)

                state = await self.agent_factory().run(
                    candidate=candidate_to_schema(candidate_row),
                    job=job_with_match.job,
                    matched_skills=job_with_match.match.matched_skills if job_with_match.match else [],
                    resume_path=candidate_row.resume_path,
                    cover_letter=row.cover_letter,
                    cover_letter_source=row.cover_letter_source,
                    submit=submit,
                    screenshot_path=settings.screenshots_dir / f"{row.id}.png",
                )
                await repo.update(
                    row,
                    cover_letter=state["cover_letter"],
                    cover_letter_source=state["cover_letter_source"],
                    **_result_fields(state["fill_result"], submit),
                )
            except Exception as exc:
                logger.exception("Application %s failed", application_id)
                await repo.update(row, status=ApplicationStatus.FAILED.value, error=str(exc))

    async def draft_cover_letter(self, application_id: str) -> None:
        """Background task for manual applications: a letter to paste into the company's form."""
        async with self.session_factory() as session:
            repo = ApplicationRepository(session)
            row = await repo.get(application_id)
            if row is None or row.cover_letter:
                return
            try:
                candidate_row = await CandidateRepository(session).get_model(row.candidate_id)
                job_row = await session.get(JobModel, row.job_id)
                if candidate_row is None or job_row is None:
                    return
                job_with_match = job_repository.to_schema(job_row)
                letter, source = await self.agent_factory().tailoring.generate_cover_letter(
                    candidate_to_schema(candidate_row),
                    job_with_match.job,
                    job_with_match.match.matched_skills if job_with_match.match else [],
                )
                # Only the letter fields are written, so a status the user set meanwhile is kept.
                await repo.update(row, cover_letter=letter, cover_letter_source=source)
            except Exception:
                logger.exception("Cover letter draft failed for %s", application_id)

    async def recover_interrupted(self) -> int:
        """Mark applications left in-flight by a previous process as failed so they can be retried."""
        async with self.session_factory() as session:
            repo = ApplicationRepository(session)
            stuck = await repo.list_all(IN_FLIGHT)
            for row in stuck:
                await repo.update(row, status=ApplicationStatus.FAILED.value, error="Interrupted by a service restart")
            return len(stuck)


def _result_fields(result: FillResult, submitted: bool) -> dict:
    status = {
        FillOutcome.SUBMITTED: ApplicationStatus.APPLIED,
        FillOutcome.FILLED: ApplicationStatus.PENDING_APPROVAL,
        FillOutcome.NEEDS_MANUAL: ApplicationStatus.NEEDS_MANUAL,
        FillOutcome.FAILED: ApplicationStatus.FAILED,
    }[result.outcome]
    message = result.message
    if result.outcome == FillOutcome.FILLED and (result.missing_required or result.captcha_detected):
        notes = []
        if result.missing_required:
            notes.append("Needs your input: " + ", ".join(result.missing_required[:8]))
        if result.captcha_detected:
            notes.append("CAPTCHA on page; you will need to submit manually")
        message = ". ".join(notes)
    return {
        "status": status.value,
        "filled_fields": result.filled_fields,
        "missing_fields": result.missing_required,
        "screenshot_path": result.screenshot_path,
        "confirmation": result.confirmation,
        "error": message,
        "applied_at": datetime.now(UTC) if submitted and result.outcome == FillOutcome.SUBMITTED else None,
    }
