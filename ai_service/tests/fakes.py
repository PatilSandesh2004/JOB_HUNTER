"""Test doubles for external systems."""

from ai_service.app.core.config import settings
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.schemas.search import RawJobPosting

FAKE_POSTINGS = [
    RawJobPosting(
        title="Job Application for AI Engineer at Optiver",
        url="https://job-boards.greenhouse.io/optiverus/jobs/7962512002",
        snippet="Python, LangGraph and FastAPI. Remote (India). 3+ years of experience.",
        source="searxng",
    ),
    RawJobPosting(
        title="Senior Accountant - Ledger Co",
        url="https://ledger.example/careers/accountant",
        snippet="Excel and IFRS. On-site in Mumbai. We do not offer visa sponsorship.",
        source="searxng",
    ),
    RawJobPosting(
        title="Backend Engineer",
        url="https://remotive.com/remote-jobs/software-dev/backend-engineer-1",
        snippet="Docker, PostgreSQL, Python.",
        company="Remote First Inc",
        location="Worldwide",
        remote=True,
        source="remotive",
    ),
    RawJobPosting(
        title="Python Backend Engineer",
        url="https://jobs.lever.co/acme/0b9f5c1e-1111-2222-3333-444455556666",
        snippet="FastAPI and PostgreSQL. On-site.",
        company="Acme",
        location="Bangalore, Karnataka, India",
        source="searxng",
    ),
    RawJobPosting(
        title="AI Engineer",
        url="https://jobs.ashbyhq.com/berlinco/0b9f5c1e-aaaa-bbbb-cccc-444455556666",
        snippet="LangGraph agents.",
        company="Berlin Co",
        location="Berlin, Germany",
        workplace="ONSITE",
        source="searxng",
    ),
    RawJobPosting(
        title="AI Engineer (Remote)",
        url="https://job-boards.greenhouse.io/usco/jobs/123456",
        snippet="LLM agents in Python.",
        company="US Co",
        location="Remote - United States",
        workplace="REMOTE",
        source="searxng",
    ),
]


class FakeSearchService:
    def __init__(self, postings=None, errors=None) -> None:
        self.postings = FAKE_POSTINGS if postings is None else postings
        self.errors = errors or []
        self.calls: list[list[str]] = []

    async def search_many(self, queries, titles, locations=None):
        self.calls.append(queries)
        return list(self.postings), list(self.errors)


def offline_llm() -> LLMClient:
    return LLMClient(settings.model_copy(update={"groq_api_key": ""}))
