"""API flows for the answer bank, open questions, re-fill, tailored resumes and the activity timeline."""

from ai_service.app.core.config import settings
from ai_service.app.integrations.browser.form_filler import FillOutcome, FillResult
from ai_service.app.services.screening.answer_bank import normalize_question
from ai_service.tests.fakes import RESUME

QUESTION = "How did you hear about us? *"


async def _setup(client, **preferences) -> str:
    """Profile with real work experience, plus the stored Acme job (auto-fillable)."""
    profile = (
        await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    ).json()
    profile["work_experience"] = [
        {
            "company": "Acme Corp",
            "title": "Backend Engineer",
            "start_date": "Jan 2020",
            "description": "Built FastAPI services on PostgreSQL.\nMentored two interns.",
        }
    ]
    profile["preferences"] |= preferences
    assert (await client.put("/api/v1/candidates/me", json=profile)).status_code == 200
    results = (
        await client.post("/api/v1/search", json={"roles": ["Backend Engineer"], "strict_location": False})
    ).json()["results"]
    return next(r["job"]["id"] for r in results if r["job"]["company"] == "Acme")


async def _app(client, app_id):
    return (await client.get(f"/api/v1/applications/{app_id}")).json()


def _filled_with_question() -> FillResult:
    result = FillResult(FillOutcome.FILLED, {"Email": "email"}, missing_required=[QUESTION])
    result.unanswered = [{"label": QUESTION, "kind": "text", "options": [], "required": True}]
    result.events = [{"at": "2026-10-06T10:00:00+00:00", "step": "Filled the form", "detail": "", "screenshot": None}]
    return result


async def test_answer_bank_crud(client):
    saved = await client.put(
        "/api/v1/screening-answers",
        json=[
            {"question": "How did you hear about us? *", "answer": "LinkedIn"},
            {"question": "Pronouns", "answer": ""},
        ],
    )
    assert saved.status_code == 200
    assert [(a["question"], a["answer"]) for a in saved.json()] == [("How did you hear about us? *", "LinkedIn")]

    # Same question with different punctuation updates the existing answer instead of adding one.
    updated = (
        await client.put(
            "/api/v1/screening-answers", json=[{"question": "how did you hear about us", "answer": "Referral"}]
        )
    ).json()
    assert len(updated) == 1 and updated[0]["answer"] == "Referral"

    removed = await client.put(
        "/api/v1/screening-answers", json=[{"question": "How did you hear about us?", "answer": ""}]
    )
    assert removed.json() == []
    assert (await client.delete("/api/v1/screening-answers/nope")).status_code == 404


async def test_open_questions_get_suggestions_then_saved_answers_are_used(client):
    job_id = await _setup(client)
    client.filler.script = [_filled_with_question()]
    client.suggester.answers = {QUESTION: "Through LinkedIn"}
    app_id = (await client.post("/api/v1/applications", json={"job_id": job_id})).json()["id"]
    await client.runner.run_due_once()

    app = await _app(client, app_id)
    assert app["status"] == "PENDING_APPROVAL"
    assert app["questions"] == [
        {"label": QUESTION, "kind": "text", "options": [], "required": True, "suggestion": "Through LinkedIn"}
    ]
    steps = [e["step"] for e in app["events"]]
    assert steps[0] == "Application created"
    assert "Cover letter written" in steps and "Filled the form" in steps
    assert steps[-1] == "Drafted answers for you to check"

    # The user accepts the suggestion and asks for a re-fill: the filler now gets the saved answer.
    await client.put("/api/v1/screening-answers", json=[{"question": QUESTION, "answer": "Through LinkedIn"}])
    refill = await client.post(f"/api/v1/applications/{app_id}/refill")
    assert refill.status_code == 202 and refill.json()["status"] == "PROCESSING"
    await client.runner.run_due_once()
    packet = client.filler.calls[-1]["packet"]
    assert packet.answers.saved[normalize_question(QUESTION)] == "Through LinkedIn"
    app = await _app(client, app_id)
    assert app["status"] == "PENDING_APPROVAL" and app["questions"] == []
    assert "Re-filling the form" in [e["step"] for e in app["events"]]

    # Re-fill is refused while the agent is busy.
    await client.post(f"/api/v1/applications/{app_id}/approve")
    assert (await client.post(f"/api/v1/applications/{app_id}/refill")).status_code == 409


async def test_tailored_resume_is_created_attached_and_reused(client):
    job_id = await _setup(client, tailor_resume=True)
    app_id = (await client.post("/api/v1/applications", json={"job_id": job_id})).json()["id"]
    await client.runner.run_due_once()

    app = await _app(client, app_id)
    tailored = settings.resumes_dir / "tailored" / f"{app_id}.pdf"
    assert app["has_tailored_resume"] is True
    assert client.filler.calls[-1]["packet"].resume_path == str(tailored)
    assert "Built <strong>FastAPI</strong> services" in client.renderer.calls[0]
    assert app["resume_report"]["matched_skills"]  # FastAPI / PostgreSQL from the Acme posting
    assert "Tailored resume created" in [e["step"] for e in app["events"]]

    pdf = await client.get(f"/api/v1/applications/{app_id}/resume")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    # Approving reuses the same PDF instead of rendering a new one.
    await client.post(f"/api/v1/applications/{app_id}/approve")
    await client.runner.run_due_once()
    assert len(client.renderer.calls) == 1
    assert client.filler.calls[-1]["packet"].resume_path == str(tailored)


async def test_tailoring_is_opt_in(client):
    job_id = await _setup(client)
    app_id = (await client.post("/api/v1/applications", json={"job_id": job_id})).json()["id"]
    await client.runner.run_due_once()
    app = await _app(client, app_id)
    assert app["has_tailored_resume"] is False and client.renderer.calls == []
    assert app["resume_report"] is not None  # the keyword-gap report is always produced
    assert (await client.get(f"/api/v1/applications/{app_id}/resume")).status_code == 404


async def test_step_screenshots_are_served_only_for_their_application(client):
    job_id = await _setup(client)
    app_id = (await client.post("/api/v1/applications", json={"job_id": job_id})).json()["id"]
    shot = settings.screenshots_dir / f"{app_id}-fill1-filled.png"
    shot.write_bytes(b"\x89PNG fake")

    ok = await client.get(f"/api/v1/applications/{app_id}/screenshots/{shot.name}")
    assert ok.status_code == 200 and ok.content == b"\x89PNG fake"
    for bad in ("other-fill1-filled.png", f"{app_id}-x.txt", "..%2F..%2Fsecret.png"):
        assert (await client.get(f"/api/v1/applications/{app_id}/screenshots/{bad}")).status_code == 404
