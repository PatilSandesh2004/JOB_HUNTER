import json

import httpx
import pytest

from ai_service.app.services.search.board_source import BoardSearchSource

GREENHOUSE = {
    "jobs": [
        {
            "title": "Senior Machine Learning Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
            "location": {"name": "Bengaluru, India"},
            "company_name": "Acme",
        },
        {
            "title": "AI Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/2",
            "location": {"name": "San Francisco, CA"},
            "company_name": "Acme",
        },
        {
            "title": "Account Executive",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/3",
            "location": {"name": "Bangalore"},
            "company_name": "Acme",
        },
        {
            "title": "AI Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/4",
            "location": {"name": "Remote - India"},
            "company_name": "Acme",
        },
    ]
}
LEVER = [
    {
        "text": "Backend Engineer (Python)",
        "hostedUrl": "https://jobs.lever.co/beta/11111111-2222-3333-4444-555555555555",
        "categories": {"location": "Bangalore", "allLocations": ["Bangalore"]},
        "workplaceType": "hybrid",
        "descriptionPlain": "FastAPI, PostgreSQL",
        "lists": [],
    },
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
    assert json.loads((tmp_path / "boards.json").read_text()) == {"discovered": {"lever": ["newco"]}, "watched": {}}
    assert ("lever", "newco") in make_source(tmp_path).boards()  # reloaded from disk


# Payload shapes taken from the live public APIs (2026-10).
RECRUITEE = {
    "offers": [
        {
            "title": "AI Engineer",
            "slug": "ai-engineer",
            "careers_url": "https://careers.gamma.com/o/ai-engineer",
            "company_name": "Gamma",
            "location": "Bengaluru, Karnataka, India",
            "city": "Bengaluru",
            "remote": False,
            "hybrid": True,
            "description": "<p>Build <b>LangGraph</b> agents in Python.</p>",
            "requirements": "<ul><li>3+ years</li></ul>",
        }
    ]
}
SMARTRECRUITERS = {
    "totalFound": 1,
    "content": [
        {
            "id": "744000153798739",
            "name": "Machine Learning Engineer",
            "company": {"identifier": "Delta2", "name": "Delta"},
            "location": {"city": "Bengaluru", "country": "in", "remote": False, "fullLocation": "Bengaluru, India"},
        }
    ],
}
WORKABLE = {
    "name": "Epsilon",
    "jobs": [
        {
            "title": "Applied AI Engineer",
            "shortcode": "81B46579FE",
            "url": "https://apply.workable.com/j/81B46579FE",
            "telecommuting": True,
            "city": "",
            "country": "India",
            "description": "<p>LLM evaluation</p>",
        }
    ],
}
PERSONIO = b"""<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs><position><id>1834171</id><subcompany>Zeta GmbH</subcompany><office>Bengaluru</office>
<additionalOffices><office>Remote</office></additionalOffices><name>AI Engineer</name>
<jobDescriptions><jobDescription><name>Your tasks</name>
<value>&lt;p&gt;Python and RAG&lt;/p&gt;</value></jobDescription></jobDescriptions>
</position></workzag-jobs>"""


def more_boards(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.startswith("https://gamma.recruitee.com/api/offers"):
        return httpx.Response(200, json=RECRUITEE)
    if "api.smartrecruiters.com/v1/companies/delta2/postings" in url:
        return httpx.Response(200, json=SMARTRECRUITERS)
    if "apply.workable.com/api/v1/widget/accounts/epsilon" in url:
        return httpx.Response(200, json=WORKABLE)
    if url.startswith("https://zeta.jobs.personio.de/xml"):
        return httpx.Response(200, content=PERSONIO, headers={"content-type": "text/xml"})
    return httpx.Response(404)


def more_source(tmp_path) -> BoardSearchSource:
    seeds = {"recruitee": ("gamma",), "smartrecruiters": ("delta2",), "workable": ("epsilon",), "personio": ("zeta",)}
    return BoardSearchSource(tmp_path / "boards.json", transport=httpx.MockTransport(more_boards), seeds=seeds)


async def test_reads_recruitee_smartrecruiters_workable_and_personio(tmp_path):
    from ai_service.app.services.jobs.ats import detect_ats

    postings = await more_source(tmp_path).search(["AI Engineer", "Machine Learning Engineer"], ["Bengaluru", "Remote"])
    by_company = {p.company: p for p in postings}
    assert set(by_company) == {"Gamma", "Delta", "Epsilon", "Zeta GmbH"}
    assert by_company["Gamma"].url == "https://gamma.recruitee.com/o/ai-engineer"  # not the custom domain
    assert "LangGraph agents" in by_company["Gamma"].snippet and by_company["Gamma"].workplace == "HYBRID"
    assert by_company["Delta"].url == "https://jobs.smartrecruiters.com/delta2/744000153798739"
    assert by_company["Epsilon"].url == "https://apply.workable.com/epsilon/j/81B46579FE/"
    assert by_company["Epsilon"].workplace == "REMOTE"
    assert (
        by_company["Zeta GmbH"].location == "Bengaluru; Remote" and "Python and RAG" in by_company["Zeta GmbH"].snippet
    )
    # Every posting can be auto-filled by the browser agent.
    assert all(detect_ats(p.url).auto_apply_supported for p in postings)


async def test_watchlist_add_list_forget(tmp_path):
    from ai_service.app.services.search.board_source import BoardError

    source = more_source(tmp_path)
    source.seeds = {}
    board, jobs = await source.watch("https://gamma.recruitee.com/o/ai-engineer")
    assert (board.ats, board.slug, board.source, jobs) == ("recruitee", "gamma", "watched", 1)
    (await source.watch("workable:epsilon"))
    assert [(b.ats, b.slug, b.source) for b in more_source(tmp_path).list_boards() if b.source == "watched"] == [
        ("recruitee", "gamma", "watched"),
        ("workable", "epsilon", "watched"),
    ]
    assert source.forget("recruitee", "gamma") and not source.forget("recruitee", "gamma")
    with pytest.raises(BoardError):
        await source.watch("https://www.linkedin.com/company/gamma")
    with pytest.raises(BoardError):
        await source.watch("https://jobs.lever.co/nobody")  # board API answers 404


def test_reads_the_old_registry_format(tmp_path):
    (tmp_path / "boards.json").write_text(json.dumps({"lever": ["oldco"]}))
    boards = BoardSearchSource(tmp_path / "boards.json", seeds={}).list_boards()
    assert [(b.ats, b.slug, b.source) for b in boards] == [("lever", "oldco", "discovered")]


@pytest.mark.parametrize(
    ("url", "posting"),
    [
        ("https://www.naukri.com/job-listings-ai-engineer-acme-bengaluru-3-to-5-years-061025000123", True),
        ("https://www.naukri.com/ai-engineer-jobs-in-bangalore", False),
        ("https://in.linkedin.com/jobs/view/ai-engineer-at-acme-4012345678", True),
        ("https://www.linkedin.com/jobs/search/?keywords=ai", False),
        ("https://in.indeed.com/viewjob?jk=abc123", True),
    ],
)
def test_job_site_postings_are_recognised(url, posting):
    from ai_service.app.services.jobs.ats import detect_ats

    info = detect_ats(url)
    assert info.name == "aggregator" and info.is_posting is posting and not info.auto_apply_supported


@pytest.mark.parametrize(
    ("page_title", "url", "expected"),
    [
        (
            "Acme hiring Senior AI Engineer in Bengaluru, Karnataka, India | LinkedIn",
            "https://in.linkedin.com/jobs/view/senior-ai-engineer-at-acme-4012345678",
            ("Senior AI Engineer", "Acme", "Bengaluru, Karnataka, India"),
        ),
        (
            "AI Job Fever hiring GEN AI Engineer in Bengaluru East ... - LinkedIn",
            "https://in.linkedin.com/jobs/view/gen-ai-engineer-at-ai-job-fever-4472000001",
            ("GEN AI Engineer", "AI Job Fever", "Bengaluru East"),
        ),
        (
            "Junior AI Engineer - Backend Python - Acme Corp - LinkedIn",
            "https://in.linkedin.com/jobs/view/junior-ai-engineer-backend-python-at-acme-corp-4471234567",
            ("Junior AI Engineer - Backend Python", "Acme Corp", "Unknown"),
        ),
        (
            "Senior AI Engineer-Hybrid-Bengaluru - LinkedIn",
            "https://in.linkedin.com/jobs/view/senior-ai-engineer-hybrid-bengaluru-at-tekion-4470000002",
            ("Senior AI Engineer-Hybrid-Bengaluru", "Tekion", "Unknown"),
        ),
        (
            "C5i hiring Gen AI Engineer in Bengaluru | LinkedIn",
            "https://in.linkedin.com/jobs/view/gen-ai-engineer-at-c5i-4474284146",
            ("Gen AI Engineer", "C5i", "Bengaluru"),
        ),
    ],
)
def test_linkedin_search_titles_are_split(page_title, url, expected):
    from ai_service.app.schemas.search import RawJobPosting
    from ai_service.app.services.jobs.normalization_service import JobNormalizationService

    job = JobNormalizationService().normalize(RawJobPosting(title=page_title, url=url, source="searxng"))
    assert (job.title, job.company, job.location) == expected


def test_job_sites_are_searched_for_the_leading_query_only():
    from ai_service.app.core.config import settings
    from ai_service.app.services.search.search_service import SearchService

    queries = SearchService(config=settings)._expand_ats_queries(["AI Engineer Bengaluru", "ML Engineer Bengaluru"])
    assert "AI Engineer Bengaluru site:naukri.com" in queries
    assert "AI Engineer Bengaluru site:linkedin.com/jobs/view" in queries
    assert not any(q.startswith("ML Engineer") and "naukri" in q for q in queries)
