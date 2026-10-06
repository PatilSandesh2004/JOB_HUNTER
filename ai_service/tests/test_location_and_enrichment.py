import httpx
import pytest

from ai_service.app.schemas.job import NormalizedJob, RemoteScope, WorkplaceType
from ai_service.app.schemas.search import RawJobPosting
from ai_service.app.services.jobs.ats import apply_page_url, detect_ats
from ai_service.app.services.jobs.enrichment_service import JobEnrichmentService
from ai_service.app.services.jobs.location_service import LocationFit, LocationMatcher


def job(location: str, workplace=WorkplaceType.UNKNOWN, title="Engineer", scope=RemoteScope.UNKNOWN) -> NormalizedJob:
    return NormalizedJob(
        id="j",
        title=title,
        company="c",
        location=location,
        workplace_type=workplace,
        remote_scope=scope,
        application_url="https://x.example/jobs/1",
    )


REMOTE = WorkplaceType.REMOTE


@pytest.mark.parametrize(
    ("wanted", "posting", "expected"),
    [
        (["Bengaluru"], job("Bangalore, Karnataka, India"), LocationFit.MATCH),
        (["Bengaluru"], job("Unknown", title="AI Engineer - Bengaluru"), LocationFit.MATCH),
        (["Bengaluru"], job("Hyderabad, India"), LocationFit.MISMATCH),
        (["Bengaluru"], job("Austin; Texas; USA"), LocationFit.MISMATCH),
        (["Bengaluru"], job("Unknown"), LocationFit.UNKNOWN),
        (["Bengaluru"], job("Remote", REMOTE), LocationFit.UNKNOWN),  # remote not requested
        (["Bengaluru", "Remote"], job("Remote", REMOTE), LocationFit.REMOTE_OK),
        (["Bengaluru", "Remote"], job("Worldwide", REMOTE), LocationFit.REMOTE_OK),
        (["Bengaluru", "Remote"], job("India; Pakistan; Egypt", REMOTE), LocationFit.REMOTE_OK),
        (["Bengaluru", "Remote"], job("APAC", REMOTE), LocationFit.REMOTE_OK),
        (["Bengaluru", "Remote"], job("Lithuania", REMOTE), LocationFit.MISMATCH),
        (["Bengaluru", "Remote"], job("Remote in Europe", REMOTE), LocationFit.MISMATCH),
        (["Bengaluru", "Remote"], job("Remote", REMOTE, scope=RemoteScope.US_ONLY), LocationFit.MISMATCH),
        (["India"], job("Pune, Maharashtra"), LocationFit.MATCH),
        (["India"], job("Gurgaon"), LocationFit.MATCH),
    ],
)
def test_location_fit(wanted, posting, expected):
    assert LocationMatcher.from_preferences(wanted).fit(posting) == expected


def test_auto_apply_support_by_site():
    assert detect_ats("https://job-boards.greenhouse.io/acme/jobs/123").auto_apply_supported
    assert detect_ats("https://apply.workable.com/acme/j/ABC123/").auto_apply_supported
    assert not detect_ats("https://remotive.com/remote-jobs/dev/backend-engineer-123").auto_apply_supported
    assert not detect_ats("https://www.turing.com/jobs/remote-ai-jobs").is_posting
    assert not detect_ats("https://careers.acme.example/jobs/search").is_posting
    assert (
        apply_page_url("https://apply.workable.com/acme/j/ABC123/") == "https://apply.workable.com/acme/j/ABC123/apply/"
    )


def _api(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "boards-api.greenhouse.io" in url:
        if url.endswith("/999"):
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "title": "Senior AI Engineer",
                "company_name": "INFUSE",
                "location": {"name": "Lithuania"},
                "content": "&lt;p&gt;Build LLM agents in Python.&lt;/p&gt;",
                "first_published": "2026-09-01T10:00:00Z",
            },
        )
    if "api.ashbyhq.com" in url:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": "8e955fa6-9164-483d-a190-33520c9b9250",
                        "title": "AI Engineer",
                        "location": "Austin",
                        "address": {"postalAddress": {"addressRegion": "Texas", "addressCountry": "USA"}},
                        "workplaceType": "OnSite",
                        "descriptionPlain": "RAG pipelines",
                    }
                ]
            },
        )
    if "api.lever.co" in url:
        return httpx.Response(
            200,
            json={
                "text": "Lead AI Engineer",
                "categories": {"location": "Remote", "allLocations": ["Remote"]},
                "workplaceType": "remote",
                "country": "US",
                "descriptionPlain": "Agents",
                "lists": [],
                "createdAt": 1767225600000,
            },
        )
    return httpx.Response(500)


async def test_enrichment_uses_ats_apis_and_drops_closed_postings():
    postings = [
        RawJobPosting(
            title="Senior AI Engineer (Remote, Contract)",
            url="https://job-boards.greenhouse.io/infuse/jobs/4735483005",
            source="searxng",
        ),
        RawJobPosting(title="Closed", url="https://job-boards.greenhouse.io/infuse/jobs/999", source="searxng"),
        RawJobPosting(
            title="AI Engineer",
            url="https://jobs.ashbyhq.com/aim4hire/8e955fa6-9164-483d-a190-33520c9b9250",
            source="searxng",
        ),
        RawJobPosting(
            title="Lead AI Engineer",
            url="https://jobs.lever.co/egen/60e5d630-cd2c-4be6-85be-2d27ef0da4ed",
            source="searxng",
        ),
        RawJobPosting(title="Company page", url="https://careers.acme.example/jobs/1", source="searxng"),
    ]
    enriched, closed = await JobEnrichmentService(transport=httpx.MockTransport(_api)).enrich(postings)

    assert closed == 1
    by_title = {p.title: p for p in enriched}
    gh = by_title["Senior AI Engineer"]
    assert (gh.company, gh.location, gh.verified) == ("INFUSE", "Lithuania", True)
    assert gh.snippet == "Build LLM agents in Python."
    ashby = by_title["AI Engineer"]
    assert ashby.location == "Austin; Texas; USA" and ashby.workplace == "ONSITE"
    lever = by_title["Lead AI Engineer"]
    assert lever.location == "Remote; US" and lever.workplace == "REMOTE" and lever.company == "Egen"
    assert by_title["Company page"].verified is False  # non-ATS pages pass through untouched
