"""Streamed search, job re-checks (closed postings), match-ordered listing, health."""

import json

import httpx

from ai_service.app.database.session import AsyncSessionLocal
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.schemas.match import JobWithMatch, MatchResult
from ai_service.app.services.jobs.enrichment_service import JobEnrichmentService
from ai_service.app.services.jobs.recheck_service import JobRecheckService


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events


async def test_search_stream_reports_each_stage_then_result(client):
    response = await client.post(
        "/api/v1/search/stream", json={"roles": ["Backend Engineer"], "strict_location": False}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    stages = [data["stage"] for kind, data in events if kind == "stage"]
    assert stages == ["plan_queries", "search_sources", "verify_postings", "normalize_and_filter", "rank"]
    kind, result = events[-1]
    assert kind == "result" and result["total_results"] == len(result["results"]) > 0

    stored = {j["job"]["id"] for j in (await client.get("/api/v1/jobs")).json()}
    assert stored == {r["job"]["id"] for r in result["results"]}


async def test_search_stream_rejects_bad_input_before_streaming(client):
    response = await client.post("/api/v1/search/stream", json={})  # no roles and no profile
    assert response.status_code == 400


def _job(job_id: str, url: str, score: float | None) -> JobWithMatch:
    job = NormalizedJob(id=job_id, title=f"Engineer {job_id}", company="Acme", application_url=url, ats="greenhouse")
    match = MatchResult(job_id=job_id, overall_match=score) if score is not None else None
    return JobWithMatch(job=job, match=match)


async def test_list_orders_by_match_and_unscored_last(client):
    async with AsyncSessionLocal() as session:
        await JobRepository(session).upsert_many(
            [
                _job("low", "https://job-boards.greenhouse.io/acme/jobs/1", 20),
                _job("none", "https://job-boards.greenhouse.io/acme/jobs/2", None),
                _job("high", "https://job-boards.greenhouse.io/acme/jobs/3", 90),
            ]
        )
    jobs = (await client.get("/api/v1/jobs")).json()
    assert [j["job"]["id"] for j in jobs] == ["high", "low", "none"]
    assert [j["job"]["id"] for j in (await client.get("/api/v1/jobs?limit=1")).json()] == ["high"]


async def test_recheck_marks_closed_postings_and_hides_them(client):
    async with AsyncSessionLocal() as session:
        await JobRepository(session).upsert_many(
            [
                _job("open", "https://job-boards.greenhouse.io/acme/jobs/1", 80),
                _job("gone", "https://job-boards.greenhouse.io/acme/jobs/2", 70),
                _job("flaky", "https://job-boards.greenhouse.io/acme/jobs/3", 60),
            ]
        )

    def board_api(request: httpx.Request) -> httpx.Response:
        job_number = request.url.path.rsplit("/", 1)[-1]
        return {"1": httpx.Response(200, json={"title": "Engineer"}), "2": httpx.Response(404)}.get(
            job_number, httpx.Response(503)
        )

    service = JobRecheckService(AsyncSessionLocal, JobEnrichmentService(transport=httpx.MockTransport(board_api)))
    assert await service.recheck_stale(10) == {"checked": 3, "closed": 1, "unknown": 1}

    visible = [j["job"]["id"] for j in (await client.get("/api/v1/jobs")).json()]
    assert visible == ["open", "flaky"]
    everything = (await client.get("/api/v1/jobs?include_closed=true")).json()
    assert next(j for j in everything if j["job"]["id"] == "gone")["job"]["closed_at"] is not None

    assert (await service.recheck_stale(10))["checked"] == 0  # all checked recently
    assert (await service.recheck_stale(10, min_age_hours=0))["checked"] == 2  # closed ones are skipped


async def test_rescore_covers_every_stored_job(client):
    from ai_service.tests.fakes import RESUME

    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    async with AsyncSessionLocal() as session:
        await JobRepository(session).upsert_many(
            [_job(str(i), f"https://job-boards.greenhouse.io/acme/jobs/{i}", None) for i in range(450)]
        )
    rescored = (await client.post("/api/v1/jobs/rescore?limit=1000")).json()
    assert len(rescored) == 450 and all(j["match"] is not None for j in rescored)


async def test_health_probes_the_browser(client):
    browser = (await client.get("/api/v1/health")).json()["components"]["browser"]
    assert isinstance(browser["ok"], bool) and browser["detail"]
