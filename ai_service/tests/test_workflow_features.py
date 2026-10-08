"""Application board (saved, offer, follow-ups, report), saved searches, resume versions and checks, mock
interviews and email digests."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from ai_service.app.agents.search_agent.graph import SearchAgent
from ai_service.app.api import deps
from ai_service.app.database.session import AsyncSessionLocal
from ai_service.app.main import app
from ai_service.app.models.application import ApplicationModel
from ai_service.app.models.saved_search import SavedSearchModel
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.schemas.match import JobWithMatch, MatchResult
from ai_service.app.services.notifications.alerts import MatchAlertService
from ai_service.app.services.notifications.digest import DigestService
from ai_service.app.services.search.saved_search_service import SavedSearchService
from ai_service.tests.fakes import RESUME, FakeSearchService, offline_llm

SEARCH = {"roles": ["Backend Engineer"], "strict_location": False}


async def _profile_and_job(client) -> str:
    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    results = (await client.post("/api/v1/search", json=SEARCH)).json()["results"]
    return next(r["job"]["id"] for r in results if r["job"]["company"] == "Acme")  # a Lever job: fillable


async def test_saved_job_becomes_an_application_and_moves_to_offer(client):
    job_id = await _profile_and_job(client)
    saved = (await client.post("/api/v1/applications", json={"job_id": job_id, "mode": "save"})).json()
    assert saved["status"] == "SAVED" and saved["events"][0]["step"] == "Saved"
    again = (await client.post("/api/v1/applications", json={"job_id": job_id, "mode": "save"})).json()
    assert again["id"] == saved["id"]  # saving twice keeps one entry

    started = (await client.post("/api/v1/applications", json={"job_id": job_id, "mode": "review"})).json()
    assert started["id"] == saved["id"] and started["status"] == "PROCESSING"
    assert started["events"][-1]["step"] == "Started from your saved jobs"
    await client.runner.run_due_once()
    await client.patch(f"/api/v1/applications/{saved['id']}", json={"status": "INTERVIEW"})
    offer = (await client.patch(f"/api/v1/applications/{saved['id']}", json={"status": "OFFER"})).json()
    assert offer["status"] == "OFFER"


async def test_follow_up_reminder_and_progress_report(client):
    job_id = await _profile_and_job(client)
    application = (await client.post("/api/v1/applications", json={"job_id": job_id, "mode": "manual"})).json()
    await client.patch(f"/api/v1/applications/{application['id']}", json={"status": "APPLIED"})
    assert not (await client.get(f"/api/v1/applications/{application['id']}")).json()["follow_up_due"]

    long_ago = datetime.now(UTC) - timedelta(days=10)
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(ApplicationModel)
            .where(ApplicationModel.id == application["id"])
            .values(updated_at=long_ago, applied_at=long_ago)
        )
        await session.commit()
    assert (await client.get(f"/api/v1/applications/{application['id']}")).json()["follow_up_due"]
    report = (await client.get("/api/v1/applications/report?days=30")).json()
    assert report["totals"]["applied"] == 1 and report["follow_ups_due"] == 1
    assert report["by_kind"][0]["applied"] == 1

    followed = (
        await client.post(f"/api/v1/applications/{application['id']}/follow-up", json={"note": "Emailed HR"})
    ).json()
    assert not followed["follow_up_due"] and followed["events"][-1]["step"] == "Followed up with the company"
    assert (await client.post("/api/v1/applications/report/email")).status_code == 409  # no SMTP in tests


async def test_saved_searches_run_on_schedule(client):
    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    service = SavedSearchService(
        AsyncSessionLocal, lambda: SearchAgent(FakeSearchService(), offline_llm()), MatchAlertService(85)
    )
    app.dependency_overrides[deps.get_saved_search_service] = lambda: service
    created = (
        await client.post("/api/v1/saved-searches", json={"name": "Backend", "request": SEARCH, "interval_hours": 24})
    ).json()
    assert created["last_run_at"] is None

    ran = (await client.post(f"/api/v1/saved-searches/{created['id']}/run")).json()
    assert ran["last_found"] > 0 and ran["last_new"] == ran["last_found"] and ran["last_error"] is None
    assert len((await client.get("/api/v1/jobs")).json()) == ran["last_found"]
    again = (await client.post(f"/api/v1/saved-searches/{created['id']}/run")).json()
    assert again["last_new"] == 0  # same jobs: nothing new

    assert await service.run_due() == 0  # ran just now; next run in 24 hours
    async with AsyncSessionLocal() as session:
        day_ago = datetime.now(UTC) - timedelta(hours=25)
        await session.execute(update(SavedSearchModel).values(last_run_at=day_ago))
        await session.commit()
    assert await service.run_due() == 1
    paused = (await client.patch(f"/api/v1/saved-searches/{created['id']}", json={"enabled": False})).json()
    assert paused["enabled"] is False and await service.run_due() == 0
    assert (await client.delete(f"/api/v1/saved-searches/{created['id']}")).status_code == 204
    assert (await client.get("/api/v1/saved-searches")).json() == []


AI_RESUME = b"""Asha Rao - AI version
asha.rao@example.com | +91 98765 43210 | linkedin.com/in/asha-rao
Experience: AI Engineer, Acme 2021 - 2026. Built RAG pipelines with LangChain, LLMs and Kubernetes for 2M users.
Education: B.Tech 2020. Skills: Python, LLMs, RAG, LangChain, Kubernetes
"""


def _ai_job() -> JobWithMatch:
    job = NormalizedJob(
        id="ai-job",
        title="AI Engineer",
        company="Zeta",
        description="Build RAG with LangChain on Kubernetes. Requirements: Python, LLMs, RAG, LangChain, Kubernetes.",
        required_skills=["Python", "LLMs", "RAG", "LangChain", "Kubernetes"],
        application_url="https://jobs.lever.co/zeta/0b9f5c1e-1111-2222-3333-444455556666",
        ats="lever",
    )
    return JobWithMatch(job=job, match=MatchResult(job_id="ai-job", overall_match=80))


async def test_resume_versions_and_resume_check(client):
    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    added = await client.post(
        "/api/v1/candidates/me/resumes", files={"file": ("ai.txt", AI_RESUME, "text/plain")}, data={"label": "AI"}
    )
    assert added.status_code == 201 and {"LLMs", "RAG", "Kubernetes"} <= set(added.json()["skills"])
    listed = (await client.get("/api/v1/candidates/me/resumes")).json()
    assert [r["label"] for r in listed] == ["Main resume", "AI"]

    async with AsyncSessionLocal() as session:
        await JobRepository(session).upsert_many([_ai_job()])
    check = (await client.get("/api/v1/jobs/ai-job/resume-check")).json()
    assert check["resume"] == "AI"  # the version that fits this job best
    assert check["keyword_coverage"] == 100.0 and {c["check"] for c in check["checks"]} >= {"Contact details", "Length"}
    main = (await client.get("/api/v1/jobs/ai-job/resume-check", params={"variant_id": "missing"})).status_code
    assert main == 404

    # Applying attaches the best version automatically.
    application = (await client.post("/api/v1/applications", json={"job_id": "ai-job", "mode": "review"})).json()
    await client.runner.run_due_once()
    assert client.filler.calls[-1]["packet"].resume_path.endswith(".txt")
    events = (await client.get(f"/api/v1/applications/{application['id']}")).json()["events"]
    assert any(e["step"] == "Attaching your resume version 'AI'" for e in events)

    variant_id = added.json()["id"]
    assert (await client.delete(f"/api/v1/candidates/me/resumes/{variant_id}")).status_code == 204
    assert [r["label"] for r in (await client.get("/api/v1/candidates/me/resumes")).json()] == ["Main resume"]


async def test_mock_interview_without_llm_asks_prepared_questions(client):
    job_id = await _profile_and_job(client)
    application = (await client.post("/api/v1/applications", json={"job_id": job_id, "mode": "manual"})).json()
    url = f"/api/v1/applications/{application['id']}/mock-interview"
    messages: list[dict] = []
    first = (await client.post(url, json={"messages": messages})).json()
    assert first["question"].startswith("Tell me about yourself") and not first["done"]
    for _ in range(10):
        turn = (await client.post(url, json={"messages": messages})).json()
        if turn["done"]:
            break
        messages += [
            {"role": "interviewer", "content": turn["question"]},
            {"role": "candidate", "content": "An answer"},
        ]
    assert turn["done"] and turn["summary"]
    bad = await client.post(url, json={"messages": [{"role": "hacker", "content": "x"}]})
    assert bad.status_code == 422


class RecordingEmail:
    configured = True

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_matches(self, items, subject=None):
        self.sent.append(subject)
        return True

    async def send(self, subject, html_body, text_body):
        self.sent.append(subject)
        return True


async def test_digest_and_weekly_emails_go_out_when_due(client, tmp_path, monkeypatch):
    from ai_service.app.core.config import settings

    async with AsyncSessionLocal() as session:
        await JobRepository(session).upsert_many([_ai_job()])
    email = RecordingEmail()
    monkeypatch.setattr(settings, "alert_digest_hours", 24)
    monkeypatch.setattr(settings, "weekly_report_email", True)
    digest = DigestService(AsyncSessionLocal, email, state_path=tmp_path / "digests.json")
    await digest.run_due()
    assert email.sent == []  # the first period starts now
    old = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    (tmp_path / "digests.json").write_text(f'{{"matches": "{old}", "weekly": "{old}"}}')
    await digest.run_due()
    assert email.sent[0] == "JobPilot digest: 1 new match" and email.sent[1].startswith("JobPilot weekly")
    await digest.run_due()
    assert len(email.sent) == 2  # not again until the next period
