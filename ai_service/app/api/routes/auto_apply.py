# Auto-apply API routes for JobPilot
"""
Endpoints:
  POST /auto-apply/start           – Create an auto‑mode application, return its ID + SSE stream URL.
  GET  /auto-apply/stream/{id}     – Server-Sent Events: streams status/question/answer/complete events.
  POST /auto-apply/captcha         – Submit a solved CAPTCHA token (answer a CAPTCHA question).
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.api.deps import get_application_service
from ai_service.app.database.session import get_db
from ai_service.app.repositories.application_repository import ApplicationRepository
from ai_service.app.schemas.application import ApplicationCreate, ApplicationStatus, ApplyMode

logger = logging.getLogger("jobpilot.auto_apply")

router = APIRouter(prefix="/auto-apply", tags=["auto-apply"])


# ──────────────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────────────


class StartRequest(BaseModel):
    job_id: str
    tailor_resume: bool | None = None


class CaptchaSubmission(BaseModel):
    application_id: str
    question_id: str  # the question label / id
    token: str


class AnswerSubmission(BaseModel):
    application_id: str
    question_id: str  # the question label / field name
    answer: str
    remember: bool = True  # save to answer bank for future applications


# ──────────────────────────────────────────────────────────────────────────────
# POST /auto-apply/start
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/start")
async def start_auto_apply(
    payload: StartRequest | None = None,
    job_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    service=Depends(get_application_service),
):
    """
    Create an auto‑mode application and return the SSE stream URL.
    Accepts either a JSON body {"job_id": ...} OR a query‑param ?job_id=...
    """
    resolved_job_id = (payload.job_id if payload else None) or job_id
    if not resolved_job_id:
        raise HTTPException(status_code=422, detail="job_id is required")

    tailor = payload.tailor_resume if payload else None
    app = await service.create(
        db,
        ApplicationCreate(job_id=resolved_job_id, mode=ApplyMode.AUTO, tailor_resume=tailor),
    )
    stream_url = f"/api/v1/auto-apply/stream/{app.id}"
    return {"application_id": app.id, "stream_url": stream_url}


# ──────────────────────────────────────────────────────────────────────────────
# GET /auto-apply/stream/{application_id}
# ──────────────────────────────────────────────────────────────────────────────

_TERMINAL = {
    ApplicationStatus.APPLIED,
    ApplicationStatus.FAILED,
    ApplicationStatus.DISMISSED,
    ApplicationStatus.AWAITING_CONFIRMATION,
}

_POLL_INTERVAL = 2.0  # seconds between DB polls
_TIMEOUT = 900  # give up after 15 minutes


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/stream/{application_id}")
async def auto_apply_stream(
    application_id: str,
    service=Depends(get_application_service),
):
    """
    Long-poll the application row and emit SSE events the frontend understands:
      status   – human-readable status update
      question – a question the agent could not auto-answer (NEEDS_INPUT)
      answer   – placeholder answer filled by agent (emitted when questions are resolved)
      complete – application submitted / done
      error    – terminal failure
    """

    async def event_generator():
        seen_questions: set[str] = set()
        prev_status: str | None = None
        elapsed = 0.0

        yield _sse("status", {"message": "Connecting to agent…"})

        while elapsed < _TIMEOUT:
            # Open a fresh session per poll to avoid stale-cache issues
            async with service.session_factory() as session:
                repo = ApplicationRepository(session)
                row = await repo.get(application_id)

            if row is None:
                yield _sse("error", {"message": f"Application {application_id} not found"})
                return

            status = ApplicationStatus(row.status)

            # Emit status change notification
            if row.status != prev_status:
                prev_status = row.status
                friendly = {
                    "PROCESSING": "📋 Agent is filling the form…",
                    "SUBMITTING": "🚀 Submitting the application…",
                    "NEEDS_INPUT": "⏸  Agent paused – needs your input",
                    "PENDING_APPROVAL": "👀 Ready for your review",
                    "APPLIED": "✅ Application submitted!",
                    "FAILED": "❌ Application failed",
                }.get(row.status, row.status)
                yield _sse("status", {"message": friendly})

            # Emit new NEEDS_INPUT questions
            questions = row.questions or []
            for q in questions:
                label = q.get("label") or q.get("id") or str(q)
                if label not in seen_questions:
                    seen_questions.add(label)
                    yield _sse(
                        "question",
                        {
                            "id": label,
                            "text": q.get("text") or q.get("label") or label,
                            "field_type": q.get("field_type", "text"),
                            "suggestion": q.get("suggestion") or q.get("ai_answer", ""),
                        },
                    )

            # Emit answers when questions are resolved (question disappeared from list)
            resolved_labels = seen_questions - {(q.get("label") or q.get("id") or str(q)) for q in questions}
            for label in resolved_labels:
                if label not in _answered_cache(application_id):
                    _mark_answered(application_id, label)
                    yield _sse("answer", {"id": label, "text": "(answered)"})

            # Terminal states
            if status == ApplicationStatus.APPLIED:
                yield _sse("complete", {"status": "applied", "message": "Application submitted successfully!"})
                return
            if status in _TERMINAL - {ApplicationStatus.APPLIED}:
                yield _sse("error", {"message": f"Application ended with status: {row.status}"})
                return

            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

        yield _sse("error", {"message": "Timed out waiting for the application to complete."})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


# Simple in-process cache to avoid re-emitting answer events (resets on restart, acceptable)
_answered: dict[str, set[str]] = {}


def _answered_cache(app_id: str) -> set[str]:
    return _answered.setdefault(app_id, set())


def _mark_answered(app_id: str, label: str):
    _answered_cache(app_id).add(label)


# ──────────────────────────────────────────────────────────────────────────────
# POST /auto-apply/captcha
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/captcha")
async def submit_captcha(
    payload: CaptchaSubmission,
    db: AsyncSession = Depends(get_db),
    service=Depends(get_application_service),
):
    """
    Receive a solved CAPTCHA token and answer the matching question so the agent can resume.
    """
    try:
        await service.answer_question(
            db,
            application_id=payload.application_id,
            label=payload.question_id,
            answer=payload.token,
            remember=False,
        )
    except Exception as exc:
        logger.warning("captcha submit failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "message": "CAPTCHA accepted – agent is resuming"}


# ──────────────────────────────────────────────────────────────────────────────
# POST /auto-apply/answer
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/answer")
async def submit_answer(
    payload: AnswerSubmission,
    db: AsyncSession = Depends(get_db),
    service=Depends(get_application_service),
):
    """
    Receive a plain-text answer to a NEEDS_INPUT question.
    If this was the last unanswered question the agent resumes automatically.
    """
    try:
        app = await service.answer_question(
            db,
            application_id=payload.application_id,
            label=payload.question_id,
            answer=payload.answer.strip(),
            remember=payload.remember,
        )
    except Exception as exc:
        logger.warning("answer submit failed for %s: %s", payload.application_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "ok",
        "message": "Answer saved – agent is resuming" if not app.questions else "Answer saved",
        "questions_remaining": len(app.questions or []),
    }
