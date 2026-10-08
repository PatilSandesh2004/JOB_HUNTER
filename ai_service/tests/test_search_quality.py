"""Search quality: role understanding, skills, requirements, de-duplication, scoring, query planning, feeds."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ai_service.app.agents.search_agent.graph import SearchAgent, build_resume_queries
from ai_service.app.core.text import fix_mojibake, parse_datetime
from ai_service.app.schemas.candidate import CandidatePreferences, CandidateProfile
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.schemas.search import RawJobPosting, SearchQueryRequest
from ai_service.app.services.jobs.deduplication_service import JobDeduplicationService
from ai_service.app.services.jobs.enrichment_service import JobEnrichmentService
from ai_service.app.services.jobs.requirements import experience_range, parse_salary, split_skills
from ai_service.app.services.matching.matching_engine import MatchingEngineService, candidate_skill_profile
from ai_service.app.services.matching.roles import related_titles, role_similarity
from ai_service.app.services.search.feeds import HimalayasFeed, JobicyFeed, RemoteOKFeed, RemotiveFeed
from ai_service.app.services.skills.catalog import extract_skills
from ai_service.tests.fakes import FakeSearchService, offline_llm

AI_SKILLS = ["LLMs", "RAG", "LangChain", "Python"]


# ---- role understanding ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("target", "title", "skills", "keep"),
    [
        ("AI Engineer", "Machine Learning Engineer", None, True),
        ("AI Engineer", "LLM Engineer", None, True),
        ("AI Engineer", "Software Engineer, Applied AI", None, True),
        ("AI Engineer", "Research Engineer, LLMs", None, True),
        ("AI Engineer", "Sales Engineer, AI", None, False),
        ("AI Engineer", "AI Content Writer", None, False),
        ("AI Engineer", "AI Product Manager", None, False),
        ("AI Engineer", "AI Data Annotator", None, False),
        ("AI Engineer", "Software Engineer / AI Code Trainer (Python)", None, False),
        ("AI Engineer", "Technical Recruiter - AI", None, False),
        ("AI Engineer", "Developer Advocate, AI", None, False),
        ("AI Engineer", "AI Solutions Architect", None, False),
        ("AI Engineer", "Frontend Engineer", None, False),
        # A generic title counts when its description is about the work.
        ("AI Engineer", "Software Engineer II", None, False),
        ("AI Engineer", "Software Engineer II", AI_SKILLS, True),
        ("AI Engineer", "Backend Engineer (Python)", None, False),
        ("AI Engineer", "Backend Engineer (Python)", AI_SKILLS, True),
        ("Python Developer", "Backend Engineer (Python)", None, True),
        ("Python Developer", "Java Developer", None, False),
        ("Python Developer", "Software Engineer", ["Java", "Spring"], False),
        ("Data Analyst", "BI Analyst", None, True),
        ("Data Analyst", "Business Analyst", None, False),
        ("Data Analyst", "Data Engineer", None, False),
        ("Data Engineer", "Analytics Engineer", None, True),
        ("DevOps Engineer", "Site Reliability Engineer", None, True),
        ("Frontend Developer", "React Developer", None, True),
    ],
)
def test_role_similarity_understands_job_kinds(target, title, skills, keep):
    assert (role_similarity(target, title, skills) >= 55) is keep


def test_related_titles():
    assert {"Machine Learning Engineer", "LLM Engineer"} <= set(related_titles("AI Engineer"))
    assert "Backend Engineer (Python)" in related_titles("Python Developer")
    assert "Business Analyst" not in related_titles("Data Analyst")


# ---- skills ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("React quickly to production incidents; strong Python", {"Python"}),
        ("Experience with React Native and Swift", {"Swift", "React Native"}),
        ("Power BI, Tableau, Excel, Statistics, R", {"R", "Excel", "Power BI", "Tableau", "Statistics"}),
        ("you excel at communication; Go to market plans", set()),
        ("RAG status reporting to stakeholders", set()),
        ("Build RAG pipelines with LangChain and pgvector", {"RAG", "LangChain", "Vector Databases"}),
        ("LoRA and QLoRA fine-tuning of LLMs", {"LLMs", "Fine-tuning"}),
        ("Spring 2026 internship", set()),
    ],
)
def test_skill_extraction_in_context(text, expected):
    assert set(extract_skills(text)) == expected


def test_candidate_free_text_skills():
    known, custom = candidate_skill_profile(
        ["SQL (PostgreSQL)", "Hugging Face Transformers", "Agentic AI", "Groq", "Communication", "MCP"]
    )
    assert {"SQL", "PostgreSQL", "Hugging Face", "AI Agents", "MCP"} <= known
    assert custom == ["Groq"]  # soft skills are ignored


# ---- requirements ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3-5 yrs of experience in Python", (3, 5)),
        ("Experience: 0-2 years", (0, 2)),
        ("Minimum five years of experience", (5, None)),
        ("We have grown for 12 years. Need 4+ years experience", (4, None)),
        ("2+ years experience; 1 year with LLMs preferred", (2, None)),
        ("Founded 15 years ago. You have 3+ years of professional experience.", (3, None)),
        ("5+ years in software engineering experience, 2+ years with Kafka", (5, None)),
        ("Freshers can apply. Strong DSA.", (0, 1)),
        ("We offer 2 years of free coaching", (None, None)),
    ],
)
def test_experience_range(text, expected):
    assert experience_range(text) == tuple(None if v is None else float(v) for v in expected)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CTC: 12-18 LPA", ("INR", 1_200_000, 1_800_000, "year")),
        ("Salary ₹12L - ₹18L per annum", ("INR", 1_200_000, 1_800_000, "year")),
        ("INR 8,00,000 - 12,00,000", ("INR", 800_000, 1_200_000, "year")),
        ("$120k - $150k + equity", ("USD", 120_000, 150_000, "year")),
        ("$40-60/hr contract", ("USD", 40, 60, "hour")),
        ("We raised $50M - $100M from investors", None),
        ("3-5 years of experience", None),
    ],
)
def test_salary_parsing(text, expected):
    salary = parse_salary(text)
    assert (None if salary is None else (salary.currency, salary.minimum, salary.maximum, salary.period)) == expected


def test_required_and_nice_to_have_skills():
    text = (
        "About us: we use Python internally. Responsibilities: build RAG pipelines with LangChain. "
        "Requirements: Python, FastAPI, PostgreSQL. Nice to have: Kubernetes, Terraform. Benefits: Docker swag."
    )
    required, preferred = split_skills(text)
    assert set(required) == {"Python", "RAG", "LangChain", "FastAPI", "PostgreSQL"}
    assert preferred == ["Kubernetes", "Terraform"]  # and Docker, mentioned under benefits, is ignored


# ---- de-duplication -------------------------------------------------------------------------------
def _job(job_id: str, location: str, verified: bool = False, title: str = "AI Engineer") -> NormalizedJob:
    return NormalizedJob(
        id=job_id,
        title=title,
        company="Acme",
        location=location,
        verified=verified,
        application_url=f"https://example.com/{job_id}",
    )


def test_same_title_in_two_cities_is_two_jobs_and_the_richest_copy_wins():
    jobs = [_job("toronto", "Toronto, Canada"), _job("snippet", "Unknown"), _job("blr", "Bangalore", verified=True)]
    kept = JobDeduplicationService().deduplicate(jobs)
    assert [j.id for j in kept] == ["toronto", "blr"]  # the snippet merged into the verified Bengaluru copy


# ---- scoring --------------------------------------------------------------------------------------
@pytest.fixture
def ai_candidate() -> CandidateProfile:
    return CandidateProfile(
        name="Asha",
        location="Bengaluru, India",
        current_role="AI Engineer",
        years_of_experience=1.5,
        skills=["Python", "LLMs", "RAG", "LangChain", "FastAPI", "MCP", "Groq"],
        preferences=CandidatePreferences(preferred_locations=["Bengaluru", "Remote"]),
    )


def _posting(**overrides) -> NormalizedJob:
    data = {
        "id": "p1",
        "title": "AI Engineer",
        "company": "Acme",
        "location": "Bengaluru",
        "description": "Build agents with MCP and Groq. " * 30,
        "required_skills": ["Python", "LLMs", "RAG", "MCP", "Kubernetes"],
        "preferred_skills": ["Terraform"],
        "experience_required": 1.0,
        "experience_max": 3.0,
        "application_url": "https://example.com/p1",
    }
    return NormalizedJob(**(data | overrides))


def test_skill_fit_counts_your_own_skills_and_weights_nice_to_have(ai_candidate):
    result = MatchingEngineService().evaluate_match(ai_candidate, _posting())
    assert "Groq" in result.matched_skills  # your own skill: not in the catalogue, but named in the description
    assert result.missing_skills == ["Kubernetes"] and result.missing_preferred == ["Terraform"]
    assert result.confidence == "HIGH" and result.passed_hard_filters and result.overall_match >= 80


def test_wrong_kind_of_job_scores_low_even_with_matching_skills(ai_candidate):
    result = MatchingEngineService().evaluate_match(ai_candidate, _posting(title="Sales Engineer, AI"))
    assert result.title_match < 20 and result.overall_match < 50


def test_postings_with_little_detail_are_capped(ai_candidate):
    bare = _posting(
        description="", required_skills=[], preferred_skills=[], experience_required=None, location="Unknown"
    )
    result = MatchingEngineService().evaluate_match(ai_candidate, bare)
    assert result.confidence == "LOW" and result.overall_match <= 80


def test_internships_and_senior_titles_do_not_fit_one_and_a_half_years(ai_candidate):
    engine = MatchingEngineService()
    assert not engine.evaluate_match(ai_candidate, _posting(title="AI Engineering Intern")).passed_hard_filters
    assert not engine.evaluate_match(ai_candidate, _posting(title="Senior AI Engineer")).passed_hard_filters


def test_search_and_rescore_give_the_same_score(ai_candidate):
    engine = MatchingEngineService()
    job = _posting(experience_required=3.0, experience_max=None)
    assert (
        engine.evaluate_match(ai_candidate, job, None).overall_match
        == engine.evaluate_match(ai_candidate, job).overall_match
    )


# ---- query planning from the resume ---------------------------------------------------------------
def test_resume_queries_use_relevant_skills_and_seniority(ai_candidate):
    queries = build_resume_queries(["AI Engineer"], ["Bengaluru", "Remote"], ai_candidate)
    assert queries[0] == "AI Engineer LLMs RAG Bengaluru"  # skills that belong to AI work, not FastAPI first
    assert "Junior AI Engineer Bengaluru" in queries


class CountingLLM:
    available = True

    def __init__(self) -> None:
        self.calls = 0

    async def complete_json(self, system, user, **_):
        self.calls += 1
        assert "Recent experience" in user
        return {"titles": ["Applied AI Engineer"], "queries": ["LLM Engineer Bengaluru"], "skills": ["LangGraph"]}


async def test_plan_blends_roles_related_titles_resume_and_llm(ai_candidate):
    llm = CountingLLM()
    agent = SearchAgent(FakeSearchService(postings=[]), llm)
    request = SearchQueryRequest(roles=["AI Engineer"], locations=["Bengaluru"])
    plan = await agent.plan_queries(agent.initial_state(request, ai_candidate))
    assert plan["queries"][0] == "AI Engineer Bengaluru"
    assert "AI Engineer LangGraph LLMs Bengaluru" in plan["queries"]  # the LLM's key skill leads
    assert "Machine Learning Engineer Bengaluru" in plan["queries"]  # another name for the same job
    assert "LLM Engineer Bengaluru" in plan["queries"]
    assert "Applied AI Engineer" in plan["titles"]
    await agent.plan_queries(agent.initial_state(request, ai_candidate))
    assert llm.calls == 1  # the same profile and search reuse the cached plan


async def test_date_filter_drops_old_and_undated_postings(ai_candidate):
    now = datetime.now(UTC)
    postings = [
        RawJobPosting(title="AI Engineer", url="https://a.example/jobs/1", company="New", location="Bengaluru",
                      source="remotive", posted_at=now - timedelta(days=2)),
        RawJobPosting(title="AI Engineer", url="https://a.example/jobs/2", company="Old", location="Bengaluru",
                      source="remotive", posted_at=now - timedelta(days=20)),
        RawJobPosting(title="AI Engineer", url="https://a.example/jobs/3", company="Undated", location="Bengaluru",
                      source="remotive"),
    ]  # fmt: skip
    service = FakeSearchService(postings=postings)
    agent = SearchAgent(service, offline_llm())
    response = await agent.run(
        SearchQueryRequest(roles=["AI Engineer"], locations=["Bengaluru"], posted_within="7d"), ai_candidate
    )
    assert [r.job.company for r in response.results] == ["New"]
    assert response.filtered_out["posted more than a week ago"] == 1 and response.filtered_out["no posting date"] == 1
    assert service.options["posted_within"] == "7d"  # also passed to the sources (web search time filter)


# ---- dates and text -------------------------------------------------------------------------------
def test_dates_and_broken_text():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    assert parse_datetime("3 days ago", now) == now - timedelta(days=3)
    assert parse_datetime(1767225600000) == datetime(2026, 1, 1, tzinfo=UTC)
    assert parse_datetime("2024-05-01 10:00:00 UTC") == datetime(2024, 5, 1, 10, tzinfo=UTC)
    assert parse_datetime("garbage") is None
    assert fix_mojibake("weâ€™re hiring") == "we’re hiring"


# ---- feeds ----------------------------------------------------------------------------------------
FEEDS = {
    "remotive.com": {"jobs": [
        {"title": "Machine Learning Engineer", "url": "https://remotive.com/remote-jobs/ml-1", "company_name": "R1",
         "candidate_required_location": "India", "salary": "$90k - $120k", "publication_date": "2026-10-01T10:00:00",
         "description": "<p>LLMs and RAG</p>"},
        {"title": "Sales Executive", "url": "https://remotive.com/remote-jobs/sales-1", "company_name": "R2"},
    ]},
    "remoteok.com": [
        {"legal": "terms"},
        {"position": "AI Engineer", "url": "https://remoteOK.com/remote-jobs/ai-1", "company": "OK1",
         "location": "", "salary_min": 100000, "salary_max": 140000, "date": "2026-10-02T00:00:00+00:00",
         "description": "weâ€™re building agents"},
    ],
    "himalayas.app": {"jobs": [
        {"title": "LLM Engineer", "applicationLink": "https://himalayas.app/companies/h/jobs/llm-1",
         "companyName": "H1",
         "locationRestrictions": ["India"], "minSalary": 30000, "maxSalary": 40000, "currency": "USD",
         "salaryPeriod": "annual", "pubDate": 1791390711, "description": "<p>RAG</p>"},
    ]},
    "jobicy.com": {"jobs": [
        {"jobTitle": "AI Engineer", "url": "https://jobicy.com/jobs/1-ai-engineer", "companyName": "J1",
         "jobGeo": "APAC", "pubDate": "2026-10-07T13:00:13+00:00", "jobDescription": "<p>PyTorch</p>"},
    ]},
}  # fmt: skip


async def test_feeds_filter_cache_and_read_salaries_and_dates():
    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(request.url.host)
        return httpx.Response(200, json=FEEDS[request.url.host])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        titles = ["AI Engineer", "Machine Learning Engineer"]
        remotive = RemotiveFeed()
        jobs = await remotive.fetch(titles, ["Remote"], client)
        assert [j.title for j in jobs] == ["Machine Learning Engineer"]  # the sales job is filtered out
        assert (jobs[0].salary_min, jobs[0].salary_currency, jobs[0].workplace) == (90_000, "USD", "REMOTE")
        await remotive.fetch(titles, ["Remote"], client)
        assert hits.count("remotive.com") == 1  # cached: Remotive asks for few requests a day

        ok = (await RemoteOKFeed().fetch(titles, [], client))[0]
        assert (ok.company, ok.location, ok.salary_max) == ("OK1", "Worldwide", 140000)
        assert ok.snippet == "we’re building agents" and ok.posted_at == datetime(2026, 10, 2, tzinfo=UTC)

        him = (await HimalayasFeed().fetch(titles, [], client))[0]
        assert (him.location, him.salary_period, him.source) == ("India", "year", "himalayas")
        job = (await JobicyFeed().fetch(titles, [], client))[0]
        assert (job.location, job.source) == ("APAC", "jobicy") and job.posted_at.year == 2026


# ---- company boards: dates; SmartRecruiters details ----------------------------------------------------
async def test_board_postings_carry_their_dates(tmp_path):
    from ai_service.app.services.search.board_source import BoardSearchSource

    def api(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [{
            "title": "AI Engineer", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
            "location": {"name": "Bengaluru"}, "first_published": "2026-09-09T10:50:29-04:00",
        }]})  # fmt: skip

    source = BoardSearchSource(tmp_path / "b.json", transport=httpx.MockTransport(api), seeds={"greenhouse": ("acme",)})
    (posting,) = await source.search(["AI Engineer"], ["Bengaluru"])
    assert posting.posted_at == datetime(2026, 9, 9, 14, 50, 29, tzinfo=UTC)


async def test_smartrecruiters_listings_get_their_description():
    def api(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/companies/delta2/postings/744000153798739"
        return httpx.Response(200, json={
            "name": "Machine Learning Engineer", "company": {"name": "Delta"},
            "location": {"fullLocation": "Bengaluru, India"}, "releasedDate": "2026-10-01T09:00:00.000Z",
            "jobAd": {"sections": {"companyDescription": {"text": "We use Java"},
                                   "jobDescription": {"text": "<p>Train PyTorch models</p>"},
                                   "qualifications": {"text": "<p>2+ years of experience with Python</p>"}}},
        })  # fmt: skip

    listing = RawJobPosting(
        title="Machine Learning Engineer",
        url="https://jobs.smartrecruiters.com/delta2/744000153798739",
        source="company_board",
        verified=True,
    )
    (enriched,), closed = await JobEnrichmentService(transport=httpx.MockTransport(api)).enrich([listing])
    assert closed == 0 and "PyTorch" in enriched.snippet and "Java" not in enriched.snippet
    assert enriched.posted_at == datetime(2026, 10, 1, 9, tzinfo=UTC)


async def test_greenhouse_jobs_on_company_careers_sites_still_get_their_description():
    def api(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/boards/coinbase/jobs/8175363"
        return httpx.Response(200, json={"title": "Machine Learning Engineer", "content": "<p>LLMs and PyTorch</p>"})

    listing = RawJobPosting(
        title="Machine Learning Engineer",
        url="https://www.coinbase.com/careers/positions/8175363?gh_jid=8175363",
        source="company_board",
        board="greenhouse:coinbase",
        board_job_id="8175363",
    )
    (enriched,), _ = await JobEnrichmentService(transport=httpx.MockTransport(api)).enrich([listing])
    assert enriched.verified and enriched.snippet == "LLMs and PyTorch"
