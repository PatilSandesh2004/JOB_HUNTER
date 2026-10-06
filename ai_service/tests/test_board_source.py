import json

import httpx

from ai_service.app.services.search.board_source import BoardSearchSource

GREENHOUSE = {
    "jobs": [
        {"title": "Senior Machine Learning Engineer", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
         "location": {"name": "Bengaluru, India"}, "company_name": "Acme"},
        {"title": "AI Engineer", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/2",
         "location": {"name": "San Francisco, CA"}, "company_name": "Acme"},
        {"title": "Account Executive", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/3",
         "location": {"name": "Bangalore"}, "company_name": "Acme"},
        {"title": "AI Engineer", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/4",
         "location": {"name": "Remote - India"}, "company_name": "Acme"},
    ]
}
LEVER = [
    {"text": "Backend Engineer (Python)", "hostedUrl": "https://jobs.lever.co/beta/11111111-2222-3333-4444-555555555555",
     "categories": {"location": "Bangalore", "allLocations": ["Bangalore"]}, "workplaceType": "hybrid",
     "descriptionPlain": "FastAPI, PostgreSQL", "lists": []},
]


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "boards-api.greenhouse.io/v1/boards/acme" in url:
        return httpx.Response(200, json=GREENHOUSE)
    if "api.lever.co/v0/postings/beta" in url:
        return httpx.Response(200, json=LEVER)
    return httpx.Response(404)


def make_source(tmp_path, **kw) -> BoardSearchSource:
    return BoardSearchSource(
        tmp_path / "boards.json",
        transport=httpx.MockTransport(handler),
        seeds={"greenhouse": ("acme",), "lever": ("beta",), "ashby": ("gone",)},
        **kw,
    )


async def test_filters_boards_by_role_and_location(tmp_path):
    source = make_source(tmp_path)
    postings = await source.search(["AI Engineer", "Backend Engineer"], ["Bengaluru", "Remote"])
    found = {(p.title, p.location) for p in postings}
    assert found == {
        ("Senior Machine Learning Engineer", "Bengaluru, India"),  # ML counts as AI
        ("AI Engineer", "Remote - India"),
        ("Backend Engineer (Python)", "Bangalore"),
    }
    lever = next(p for p in postings if p.title.startswith("Backend"))
    assert lever.verified and lever.workplace == "HYBRID" and lever.snippet.startswith("FastAPI")


async def test_discovered_boards_are_persisted_and_searched(tmp_path):
    source = make_source(tmp_path)
    added = source.remember_from_urls(
        ["https://jobs.lever.co/newco/11111111-2222-3333-4444-555555555555", "https://example.com/jobs/1"]
    )
    assert added == 1
    assert json.loads((tmp_path / "boards.json").read_text()) == {"lever": ["newco"]}
    assert ("lever", "newco") in make_source(tmp_path).boards()  # reloaded from disk
