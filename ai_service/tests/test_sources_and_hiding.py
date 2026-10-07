"""Not-interested jobs, blocked companies, the company-board watchlist API, scheduled discovery."""

import httpx

from ai_service.app.agents.search_agent.graph import SearchAgent
from ai_service.app.api import deps
from ai_service.app.database.session import AsyncSessionLocal
from ai_service.app.main import app
from ai_service.app.services.notifications.alerts import MatchAlertService
from ai_service.app.services.search.board_source import BoardSearchSource
from ai_service.app.services.search.discovery_service import DiscoveryService
from ai_service.tests.fakes import RESUME, FakeSearchService, offline_llm

SEARCH = {"roles": ["Backend Engineer"], "strict_location": False}


async def _profile(client) -> dict:
    return (await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})).json()


async def test_not_interested_jobs_stay_hidden(client):
    results = (await client.post("/api/v1/search", json=SEARCH)).json()["results"]
    acme = next(r["job"]["id"] for r in results if r["job"]["company"] == "Acme")

    assert (await client.post(f"/api/v1/jobs/{acme}/hide")).status_code == 204
    assert acme not in {j["job"]["id"] for j in (await client.get("/api/v1/jobs")).json()}
    assert [j["job"]["id"] for j in (await client.get("/api/v1/jobs?hidden=true")).json()] == [acme]

    # The same posting found again by a later search is not shown again.
    again = (await client.post("/api/v1/search", json=SEARCH)).json()
    assert acme not in {r["job"]["id"] for r in again["results"]}
    assert again["filtered_out"]["not interested"] == 1

    assert (await client.post(f"/api/v1/jobs/{acme}/unhide")).status_code == 204
    assert acme in {j["job"]["id"] for j in (await client.get("/api/v1/jobs")).json()}
    assert (await client.post("/api/v1/jobs/nope/hide")).status_code == 404


async def test_blocked_companies_are_left_out(client):
    profile = await _profile(client)
    await client.post("/api/v1/search", json=SEARCH)
    profile["preferences"]["blocked_companies"] = ["acme", "Remote First Inc"]
    await client.put("/api/v1/candidates/me", json=profile)

    companies = {j["job"]["company"] for j in (await client.get("/api/v1/jobs")).json()}
    assert not companies & {"Acme", "Remote First Inc"}
    search = (await client.post("/api/v1/search", json=SEARCH)).json()
    assert search["filtered_out"]["company you hid"] == 2
    assert not {r["job"]["company"] for r in search["results"]} & {"Acme", "Remote First Inc"}


def _boards_api(request: httpx.Request) -> httpx.Response:
    if str(request.url).startswith("https://api.lever.co/v0/postings/acme"):
        return httpx.Response(200, json=[{"text": "AI Engineer", "hostedUrl": "https://jobs.lever.co/acme/1"}])
    return httpx.Response(404)


async def test_board_watchlist_api(client, tmp_path):
    boards = BoardSearchSource(
        tmp_path / "boards.json", transport=httpx.MockTransport(_boards_api), seeds={"ashby": ("seedco",)}
    )
    app.dependency_overrides[deps.get_board_source] = lambda: boards

    added = await client.post("/api/v1/boards", json={"url": "https://jobs.lever.co/acme"})
    assert added.status_code == 201
    assert added.json() == {"ats": "lever", "slug": "acme", "company": "Acme", "source": "watched", "open_jobs": 1}
    listed = {(b["slug"], b["source"]) for b in (await client.get("/api/v1/boards")).json()}
    assert listed == {("acme", "watched"), ("seedco", "seed")}

    bad = await client.post("/api/v1/boards", json={"url": "https://www.naukri.com/acme-jobs"})
    assert bad.status_code == 400 and "Lever" in bad.json()["detail"]
    assert (await client.delete("/api/v1/boards/ashby/seedco")).status_code == 404  # built-in boards stay
    assert (await client.delete("/api/v1/boards/lever/acme")).status_code == 204


async def test_scheduled_discovery_uses_the_profile(client):
    discovery = DiscoveryService(
        AsyncSessionLocal, lambda: SearchAgent(FakeSearchService(), offline_llm()), MatchAlertService(85)
    )
    assert await discovery.run_once() == 0  # no profile, nothing to search for

    profile = await _profile(client)
    profile["preferences"]["preferred_roles"] = ["Backend Engineer"]
    await client.put("/api/v1/candidates/me", json=profile)
    stored = await discovery.run_once()
    assert stored > 0
    jobs = (await client.get("/api/v1/jobs")).json()
    assert len(jobs) == stored and all(j["match"] for j in jobs)
