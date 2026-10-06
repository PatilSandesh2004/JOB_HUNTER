import pytest

from ai_service.app.agents.search_agent.graph import SearchAgent, SearchInputError, build_base_queries, resolve_targets
from ai_service.app.schemas.search import SearchQueryRequest
from ai_service.tests.fakes import FakeSearchService, offline_llm


def titles(response) -> set[str]:
    return {f"{r.job.title} @ {r.job.company}" for r in response.results}


def test_base_queries_handle_remote_and_city_aliases():
    queries = build_base_queries(["AI Engineer"], ["Bengaluru", "Remote"])
    assert queries[:2] == ["AI Engineer Bengaluru", "AI Engineer remote"]
    assert "AI Engineer Bangalore" in queries  # engines index both spellings


def test_targets_default_to_profile(candidate):
    roles, locations = resolve_targets(SearchQueryRequest(), candidate)
    assert roles == ["AI Engineer", "Backend Engineer"]
    assert locations == ["Bengaluru", "Remote"]
    with pytest.raises(SearchInputError):
        resolve_targets(SearchQueryRequest(), None)


async def test_strict_location_keeps_bengaluru_and_open_remote_only(candidate):
    agent = SearchAgent(FakeSearchService(errors=["Remotive API failed: timeout"]), offline_llm())
    response = await agent.run(SearchQueryRequest(roles=["Engineer"], locations=["Bengaluru", "Remote"]), candidate)
    kept = titles(response)
    assert "Python Backend Engineer @ Acme" in kept  # "Bangalore" matches "Bengaluru"
    assert "Backend Engineer @ Remote First Inc" in kept  # remote worldwide
    assert "AI Engineer @ Optiver" in kept  # remote (India)
    assert "AI Engineer @ Berlin Co" not in kept  # other country
    assert "AI Engineer @ US Co" not in kept  # remote but US-only
    assert response.filtered_out["other location"] >= 2
    assert "Remotive API failed: timeout" in response.errors


async def test_city_only_excludes_remote(candidate):
    agent = SearchAgent(FakeSearchService(), offline_llm())
    response = await agent.run(SearchQueryRequest(roles=["Engineer"], locations=["Bengaluru"]), candidate)
    assert titles(response) == {"Python Backend Engineer @ Acme"}


async def test_unrelated_roles_are_filtered_and_rest_ranked(candidate):
    agent = SearchAgent(FakeSearchService(), offline_llm())
    request = SearchQueryRequest(roles=["AI Engineer", "Backend Engineer"], strict_location=False)
    response = await agent.run(request, candidate)
    assert "Senior Accountant @ Ledger Co" not in titles(response)
    assert response.filtered_out["unrelated role"] == 1
    assert response.total_results == 5
    scores = [r.match.overall_match for r in response.results]
    assert scores == sorted(scores, reverse=True)


async def test_sponsorship_filter(candidate):
    agent = SearchAgent(FakeSearchService(), offline_llm())
    request = SearchQueryRequest(roles=["Accountant"], sponsorship_required=True, strict_location=False)
    response = await agent.run(request, candidate)
    assert "Senior Accountant @ Ledger Co" not in titles(response)
    assert response.filtered_out["no sponsorship"] == 1


async def test_runs_without_candidate():
    agent = SearchAgent(FakeSearchService(), offline_llm())
    response = await agent.run(SearchQueryRequest(roles=["Engineer"], strict_location=False), None)
    assert response.total_results == 5  # every engineering job; the accountant is unrelated
    assert all(r.match is None for r in response.results)
