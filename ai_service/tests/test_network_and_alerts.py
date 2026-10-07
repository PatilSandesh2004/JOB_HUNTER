"""Network tab (connections, contacts, outreach), interview insights, one-time alerts and Auto-Pilot limits."""

import pytest

from ai_service.app.api import deps
from ai_service.app.core.config import settings
from ai_service.app.database.session import AsyncSessionLocal
from ai_service.app.main import app
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.connection_repository import ConnectionCsvError, parse_connections_csv
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.schemas.match import JobWithMatch, MatchResult
from ai_service.app.services.notifications.alerts import MatchAlertService
from ai_service.app.services.search.discovery_service import DiscoveryService, auto_apply_candidates
from ai_service.tests.fakes import RESUME

# LinkedIn's export starts with notes before the header row.
CONNECTIONS_CSV = b"""Notes:
"When exporting your connection data, you may notice that some of the email addresses are missing."

First Name,Last Name,URL,Email Address,Company,Position,Connected On
Priya,Shah,https://www.linkedin.com/in/priya,,Acme Corp,Senior Engineer,01 Jan 2026
Ravi,Kumar,https://www.linkedin.com/in/ravi,,Beta,Recruiter,02 Feb 2026
,,,,,,
"""


def test_connections_csv_skips_linkedins_notes():
    rows = parse_connections_csv(CONNECTIONS_CSV)
    assert [(r["first name"], r["company"]) for r in rows] == [("Priya", "Acme Corp"), ("Ravi", "Beta")]
    with pytest.raises(ConnectionCsvError):
        parse_connections_csv(b"name,email\nx,y\n")


class FakeWebSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, **_):
        self.queries.append(query)
        return [
            {
                "url": "https://in.linkedin.com/in/jane-doe",
                "title": "Jane Doe - Recruiter - Acme | LinkedIn",
                "content": "TA",
            },
            {"url": "https://www.linkedin.com/company/acme", "title": "Acme | LinkedIn", "content": "company page"},
            {"url": "https://www.linkedin.com/jobs/view/123", "title": "AI Engineer", "content": "a job"},
        ]


async def test_contacts_use_connections_and_role(client):
    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    upload = await client.post(
        "/api/v1/candidates/me/connections/upload", files={"file": ("Connections.csv", CONNECTIONS_CSV, "text/csv")}
    )
    assert upload.status_code == 200 and upload.json()["count"] == 2
    assert (await client.get("/api/v1/candidates/me/connections")).json() == {"count": 2}

    search = FakeWebSearch()
    app.dependency_overrides[deps.get_searxng] = lambda: search
    data = (
        await client.get("/api/v1/jobs/company-contacts", params={"company": "Acme", "job_title": "AI Engineer"})
    ).json()
    assert [c["first_name"] for c in data["connections"]] == ["Priya"]
    assert [p["title"] for p in data["recruiters"]] == ["Jane Doe - Recruiter - Acme"]  # company/job pages skipped
    assert any('"AI Engineer"' in q for q in search.queries)  # team members matched to the role
    assert "Acme+AI+Engineer" in data["linkedin_search_emp"]


async def test_outreach_without_llm_or_profile_uses_a_template(client):
    response = await client.post("/api/v1/jobs/outreach-message", json={"company": "Acme", "contact_name": "Jane Doe"})
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "template" and "Acme" in body["linkedin_note"] and len(body["linkedin_note"]) <= 300
    assert (await client.post("/api/v1/jobs/outreach-message", json={})).status_code == 422


async def test_interview_insights_fall_back_without_llm(client):
    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    results = (
        await client.post("/api/v1/search", json={"roles": ["Backend Engineer"], "strict_location": False})
    ).json()
    job_id = results["results"][0]["job"]["id"]
    application = (await client.post("/api/v1/applications", json={"job_id": job_id, "mode": "manual"})).json()
    insights = (await client.get(f"/api/v1/applications/{application['id']}/insights")).json()
    assert insights["source"] == "template"
    assert len(insights["behavioral_questions"]) == 5
    assert isinstance(insights["missing_skills"], list) and isinstance(insights["technical_topics"], list)
    assert (await client.get("/api/v1/applications/nope/insights")).status_code == 404


def _strong(job_id: str, score: float = 92.0, title_match: float = 95.0, verified: bool = True) -> JobWithMatch:
    job = NormalizedJob(
        id=job_id,
        title="AI Engineer",
        company="Acme",
        application_url=f"https://job-boards.greenhouse.io/acme/jobs/{int.from_bytes(job_id.encode(), 'big')}",
        ats="greenhouse",
        verified=verified,
    )
    match = MatchResult(job_id=job_id, overall_match=score, title_match=title_match, passed_hard_filters=True)
    return JobWithMatch(job=job, match=match)


class RecordingWebhook:
    configured = True

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, items):
        self.sent += [i.job.id for i in items]
        return {i.job.id for i in items}


async def test_strong_matches_are_announced_once(client):
    items = [_strong("1"), _strong("2", score=60), _strong("3")]
    async with AsyncSessionLocal() as session:
        await JobRepository(session).upsert_many(items)
        await JobRepository(session).set_hidden("3", True)
        webhook = RecordingWebhook()
        alerts = MatchAlertService(85, webhook=webhook)
        assert await alerts.notify_new(session, items) == 1  # 2 is below the threshold, 3 is hidden
        assert await alerts.notify_new(session, items) == 0  # never twice
    assert webhook.sent == ["1"]


def test_auto_pilot_only_takes_safe_jobs():
    picks = auto_apply_candidates(
        [
            _strong("ok"),
            _strong("weak-title", title_match=60),  # e.g. "AI Product Manager" for an AI Engineer
            _strong("unverified", verified=False),
            _strong("low", score=70),
            _strong("best", score=97),
        ],
        threshold=85,
    )
    assert [p.job.id for p in picks] == ["best", "ok"]


async def test_auto_pilot_respects_the_daily_limit(client, monkeypatch):
    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    profile = (await client.get("/api/v1/candidates/me")).json()
    profile["preferences"]["auto_apply_high_matches"] = True
    await client.put("/api/v1/candidates/me", json=profile)
    items = [_strong(str(i), score=90 + i) for i in range(4)]
    async with AsyncSessionLocal() as session:
        await JobRepository(session).upsert_many(items)

    monkeypatch.setattr(settings, "auto_apply_daily_limit", 2)
    discovery = DiscoveryService(AsyncSessionLocal, lambda: None, MatchAlertService(85), client.service)
    async with AsyncSessionLocal() as session:
        candidate = await CandidateRepository(session).get_active()
        assert await discovery._auto_apply(session, candidate, items) == 2
        assert await discovery._auto_apply(session, candidate, items) == 0  # the 24-hour budget is used up
    apps = (await client.get("/api/v1/applications")).json()
    assert sorted(a["job_id"] for a in apps) == ["2", "3"]  # the two best matches
    assert all(a["mode"] == "auto" for a in apps)
    assert all(any(e["step"] == "Started by Full Auto-Pilot" for e in a["events"]) for a in apps)
