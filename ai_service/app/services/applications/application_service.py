"""Application lifecycle: create -> fill (preview) -> human approval -> submit.

Agent work runs as rows in the `agent_tasks` queue (see services/tasks/runner.py), so it survives
restarts and transient failures are retried. A form fill is retried only while the submit button has
not been clicked; after that a retry could file a duplicate application, so it goes to the human.

Every step is recorded on the application's activity timeline (`events`). Required questions the agent
could not answer are stored on the application (`questions`) with AI-drafted suggestions for review;
answers the user saves go to the answer bank and are reused on every later form.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.app.agents.application_agent.graph import ApplicationAgent
from ai_service.app.core.config import settings
from ai_service.app.core.errors import JobPilotError, NotFoundError
from ai_service.app.core.timeline import timeline_event
from ai_service.app.integrations.browser.form_filler import FillOutcome, FillResult
from ai_service.app.models.application import ApplicationModel
from ai_service.app.models.job import JobModel
from ai_service.app.models.task import TaskModel
from ai_service.app.repositories import job_repository
from ai_service.app.repositories.application_repository import ApplicationRepository, to_schema
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.candidate_repository import to_schema as candidate_to_schema
from ai_service.app.repositories.screening_answer_repository import ScreeningAnswerRepository
from ai_service.app.repositories.task_repository import TaskKind, TaskRepository, TaskStatus
from ai_service.app.schemas.application import ApplicationCreate, ApplicationRead, ApplicationStatus, ApplyMode
from ai_service.app.services.jobs.ats import detect_ats
from ai_service.app.services.screening.answer_bank import AnswerBook, ScreeningSuggester
from ai_service.app.services.tasks.runner import Handler, RetryLater, TaskFailed

logger = logging.getLogger("jobpilot.applications")

APPROVABLE = {ApplicationStatus.PENDING_APPROVAL, ApplicationStatus.NEEDS_MANUAL, ApplicationStatus.FAILED}
IN_FLIGHT = {ApplicationStatus.PROCESSING, ApplicationStatus.SUBMITTING}
MANUAL_STATUSES = {
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.REJECTED,
    ApplicationStatus.DISMISSED,
}
INTERRUPTED_SUBMIT = (
    "The service stopped while submitting this application, so it may or may not have gone through. "
    "Check your email or the company site before retrying to avoid a duplicate application."
)
_MODE_EVENT = {
    ApplyMode.REVIEW: "The agent will fill the form and wait for your approval",
    ApplyMode.AUTO: "The agent will fill the form and submit it if nothing needs your input",
    ApplyMode.MANUAL: "You apply on the company site; a cover letter is drafted for you",
}


class ApplicationConflictError(JobPilotError):
    pass


class ApplicationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        agent_factory: Callable[[], ApplicationAgent],
        max_attempts: int | None = None,
        suggester: ScreeningSuggester | None = None,
    ):
        self.session_factory = session_factory
        self.agent_factory = agent_factory
        self.max_attempts = max_attempts or settings.task_max_attempts
        self.suggester = suggester
        # Set by the task runner so new work starts immediately instead of at the next poll.
        self.on_enqueue: Callable[[], None] = lambda: None

    def task_handlers(self) -> dict[str, Handler]:
        return {
            TaskKind.FILL_APPLICATION.value: self._run_fill_task,
            TaskKind.SUBMIT_APPLICATION.value: self._run_fill_task,
            TaskKind.DRAFT_COVER_LETTER.value: self._run_letter_task,
        }

    # ---- request-time operations ----------------------------------------
    async def create(self, session: AsyncSession, payload: ApplicationCreate) -> ApplicationRead:
        """Create (or reuse) an application and queue the agent work it needs."""
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
                    existing,
                    status=ApplicationStatus.AWAITING_CONFIRMATION.value,
                    mode=ApplyMode.MANUAL.value,
                    events=[timeline_event("Switched to applying yourself", _MODE_EVENT[ApplyMode.MANUAL])],
                )
            elif manual and status in IN_FLIGHT:
                raise ApplicationConflictError("The agent is still working on this application; try again shortly")
            return to_schema(existing)

        tailor = candidate.preferences.tailor_resume if payload.tailor_resume is None else payload.tailor_resume
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
            events=[timeline_event("Application created", _MODE_EVENT[payload.mode])],
            questions=[],
        )
        if not manual:
            submit = payload.mode == ApplyMode.AUTO
            await self._enqueue(session, TaskKind.FILL_APPLICATION, row.id, submit=submit, tailor=tailor)
        elif not payload.cover_letter:
            await self._enqueue(session, TaskKind.DRAFT_COVER_LETTER, row.id)
        return to_schema(row)

    async def approve(self, session: AsyncSession, application_id: str) -> ApplicationRead:
        """Human approval: queue a fill-and-submit with the (possibly edited) cover letter."""
        repo = ApplicationRepository(session)
        row = await self._get(repo, application_id)
        if ApplicationStatus(row.status) not in APPROVABLE:
            raise ApplicationConflictError(f"Cannot submit an application in status {row.status}")
        row = await repo.update(
            row,
            status=ApplicationStatus.SUBMITTING.value,
            error=None,
            events=[timeline_event("Approved by you", "The agent will fill the form again and submit it")],
        )
        await self._enqueue(session, TaskKind.SUBMIT_APPLICATION, row.id, submit=True)
        return to_schema(row)

    async def refill(self, session: AsyncSession, application_id: str) -> ApplicationRead:
        """Fill the form again without submitting, e.g. after saving answers to its open questions."""
        repo = ApplicationRepository(session)
        row = await self._get(repo, application_id)
        if ApplicationStatus(row.status) not in APPROVABLE:
            raise ApplicationConflictError(f"Cannot re-fill an application in status {row.status}")
        row = await repo.update(
            row,
            status=ApplicationStatus.PROCESSING.value,
            error=None,
            events=[timeline_event("Re-filling the form", "Using your latest profile and saved answers")],
        )
        await self._enqueue(session, TaskKind.FILL_APPLICATION, row.id)
        return to_schema(row)

    async def update(
        self, session: AsyncSession, application_id: str, cover_letter: str | None, status: ApplicationStatus | None
    ) -> ApplicationRead:
        repo = ApplicationRepository(session)
        row = await self._get(repo, application_id)
        if ApplicationStatus(row.status) in IN_FLIGHT:
            raise ApplicationConflictError("The agent is still working on this application")
        changes: dict[str, Any] = {}
        events = []
        if cover_letter is not None:
            changes |= {"cover_letter": cover_letter, "cover_letter_source": "user"}
            events.append(timeline_event("Cover letter edited by you"))
        if status is not None:
            if status not in MANUAL_STATUSES:
                raise ApplicationConflictError(f"Status {status} cannot be set manually")
            changes["status"] = status.value
            events.append(timeline_event(f"Marked as {status.value.replace('_', ' ').title()}"))
            if status == ApplicationStatus.APPLIED and row.applied_at is None:
                changes["applied_at"] = datetime.now(UTC)
        return to_schema(await repo.update(row, events=events, **changes))

    async def _enqueue(
        self, session: AsyncSession, kind: TaskKind, application_id: str, submit: bool = False, tailor: bool = False
    ) -> None:
        attempts = 1 if kind == TaskKind.DRAFT_COVER_LETTER else self.max_attempts
        await TaskRepository(session).enqueue(
            kind,
            application_id=application_id,
            payload={"submit": submit, "tailor_resume": tailor},
            max_attempts=attempts,
        )
        self.on_enqueue()

    @staticmethod
    async def _get(repo: ApplicationRepository, application_id: str) -> ApplicationModel:
        row = await repo.get(application_id)
        if row is None:
            raise NotFoundError(f"Application {application_id} not found")
        return row

    # ---- task handlers -----------------------------------------------------
    async def _run_fill_task(self, task: TaskModel) -> None:
        await self.process(
            task.application_id,
            submit=bool(task.payload.get("submit")),
            attempt=task.attempts,
            max_attempts=task.max_attempts,
            tailor_resume=bool(task.payload.get("tailor_resume")),
        )

    async def _run_letter_task(self, task: TaskModel) -> None:
        await self.draft_cover_letter(task.application_id)

    async def process(
        self, application_id: str, submit: bool, attempt: int = 1, max_attempts: int = 1, tailor_resume: bool = False
    ) -> None:
        """Draft the cover letter and fill (optionally submit) the form for one application."""
        async with self.session_factory() as session:
            repo = ApplicationRepository(session)
            row = await repo.get(application_id)
            if row is None:
                return
            retries_left = attempt < max_attempts
            started = [timeline_event("Agent started", f"Attempt {attempt} of {max_attempts}")] if attempt > 1 else []
            try:
                candidate_row = await CandidateRepository(session).get_model(row.candidate_id)
                job_row = await session.get(JobModel, row.job_id)
                if candidate_row is None or job_row is None:
                    raise NotFoundError("Candidate or job no longer exists")
                candidate = candidate_to_schema(candidate_row)
                job_with_match = job_repository.to_schema(job_row)
                answers = AnswerBook(
                    saved=await ScreeningAnswerRepository(session).as_lookup(),
                    willing_to_relocate=candidate.preferences.willing_to_relocate,
                )
                run_tag = f"{'submit' if submit else 'fill'}{attempt}"
                state = await self.agent_factory().run(
                    candidate=candidate,
                    job=job_with_match.job,
                    matched_skills=job_with_match.match.matched_skills if job_with_match.match else [],
                    resume_path=candidate_row.resume_path,
                    cover_letter=row.cover_letter,
                    cover_letter_source=row.cover_letter_source,
                    submit=submit,
                    answers=answers,
                    tailor_resume=tailor_resume,
                    tailored_resume_target=settings.resumes_dir / "tailored" / f"{row.id}.pdf",
                    existing_tailored_resume=row.tailored_resume_path,
                    screenshot_path=settings.screenshots_dir / f"{row.id}-{run_tag}.png",
                )
            except NotFoundError as exc:
                await repo.update(
                    row,
                    status=ApplicationStatus.FAILED.value,
                    error=str(exc),
                    events=[timeline_event("Failed", str(exc))],
                )
                raise TaskFailed(str(exc)) from exc
            except Exception as exc:
                logger.exception("Application %s failed (attempt %d/%d)", application_id, attempt, max_attempts)
                # Nothing reached the browser's submit step, so retrying cannot duplicate the application.
                failed = timeline_event(f"Attempt {attempt} failed", str(exc))
                if retries_left:
                    await repo.update(
                        row, error=f"Attempt {attempt} failed ({exc}); retrying shortly", events=[*started, failed]
                    )
                    raise RetryLater(str(exc)) from exc
                await repo.update(row, status=ApplicationStatus.FAILED.value, error=str(exc), events=[*started, failed])
                raise TaskFailed(str(exc)) from exc

            result: FillResult = state["fill_result"]
            events = [*started, *state.get("events", []), *result.events]
            materials = {
                "cover_letter": state["cover_letter"],
                "cover_letter_source": state["cover_letter_source"],
                "resume_report": state.get("resume_report"),
                "tailored_resume_path": state.get("tailored_resume_path") or row.tailored_resume_path,
            }
            if result.outcome == FillOutcome.FAILED and not result.submit_attempted and retries_left:
                events.append(timeline_event("Will retry", "The failure happened before submitting"))
                await repo.update(
                    row,
                    **materials,
                    error=f"Attempt {attempt} failed ({result.message}); retrying shortly",
                    events=events,
                )
                raise RetryLater(result.message or "form fill failed")

            questions = await self._suggest_answers(result.unanswered, candidate, job_with_match.job)
            if any(q.get("suggestion") for q in questions):
                events.append(timeline_event("Drafted answers for you to check", f"{len(questions)} open question(s)"))
            await repo.update(row, **materials, **_result_fields(result, submit), questions=questions, events=events)

    async def _suggest_answers(self, unanswered: list[dict], candidate, job) -> list[dict]:
        if not unanswered:
            return []
        suggestions = await self.suggester.suggest(unanswered, candidate, job) if self.suggester else {}
        return [q | {"suggestion": suggestions.get(q["label"])} for q in unanswered]

    async def draft_cover_letter(self, application_id: str) -> None:
        """Manual applications: a letter to paste into the company's form."""
        async with self.session_factory() as session:
            repo = ApplicationRepository(session)
            row = await repo.get(application_id)
            if row is None or row.cover_letter:
                return
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
            how = "by AI from your profile" if source == "llm" else "from a template (LLM unavailable)"
            await repo.update(
                row,
                cover_letter=letter,
                cover_letter_source=source,
                events=[timeline_event("Cover letter drafted", how)],
            )

    # ---- startup recovery ----------------------------------------------------
    async def recover_interrupted(self) -> int:
        """Resume work a previous process left running. Returns the number of applications affected.

        Fills that had not submitted are re-queued. A submit that was cut off may or may not have gone
        through, so it is handed to the human instead of being retried.
        """
        affected = 0
        async with self.session_factory() as session:
            tasks = TaskRepository(session)
            repo = ApplicationRepository(session)
            for task in await tasks.list_running():
                affected += 1
                row = await repo.get(task.application_id) if task.application_id else None
                if task.payload.get("submit"):
                    await tasks.finish(task.id, TaskStatus.FAILED, "Interrupted during submit")
                    if row is not None:
                        await repo.update(
                            row,
                            status=ApplicationStatus.NEEDS_MANUAL.value,
                            error=INTERRUPTED_SUBMIT,
                            events=[timeline_event("Interrupted while submitting", "Check before retrying")],
                        )
                else:
                    await tasks.finish(task.id, TaskStatus.QUEUED, "Interrupted by a service restart; resumed")
                    if row is not None:
                        await repo.update(row, events=[timeline_event("Service restarted", "Resuming the agent")])
            # Applications in flight with no task at all (e.g. from before the task queue existed).
            for row in await repo.list_all(IN_FLIGHT):
                if not await tasks.has_active(row.id):
                    affected += 1
                    await repo.update(
                        row, status=ApplicationStatus.FAILED.value, error="Interrupted by a service restart"
                    )
        return affected


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
    if result.outcome == FillOutcome.FAILED and result.submit_attempted:
        message = f"{message}. Submit may have gone through; check before retrying."
    return {
        "status": status.value,
        "filled_fields": result.filled_fields,
        "missing_fields": result.missing_required,
        "screenshot_path": result.screenshot_path,
        "confirmation": result.confirmation,
        "error": message,
        "applied_at": datetime.now(UTC) if submitted and result.outcome == FillOutcome.SUBMITTED else None,
    }
