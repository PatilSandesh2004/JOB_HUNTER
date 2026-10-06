from ai_service.app.schemas.job import RemoteScope, VisaSponsorshipStatus, WorkplaceType
from ai_service.app.schemas.search import RawJobPosting
from ai_service.app.services.jobs.ats import apply_page_url, detect_ats
from ai_service.app.services.jobs.deduplication_service import JobDeduplicationService
from ai_service.app.services.jobs.normalization_service import JobNormalizationService

normalizer = JobNormalizationService()


def raw(title: str, url: str, snippet: str = "", **kw) -> RawJobPosting:
    return RawJobPosting(title=title, url=url, snippet=snippet, source="searxng", **kw)


def test_greenhouse_title_and_company():
    job = normalizer.normalize(
        raw("Job Application for AI Engineer at Optiver", "https://job-boards.greenhouse.io/optiverus/jobs/7962512002")
    )
    assert (job.title, job.company, job.ats) == ("AI Engineer", "Optiver", "greenhouse")


def test_lever_reversed_title_uses_slug_for_company():
    job = normalizer.normalize(
        raw(
            "Acme Robotics - Senior Backend Engineer",
            "https://jobs.lever.co/acme-robotics/0b9f5c1e-1111-2222-3333-444455556666",
        )
    )
    assert job.title == "Senior Backend Engineer"
    assert job.company == "Acme Robotics"


def test_company_suffixes_are_stripped():
    gh = normalizer.normalize(
        raw("Job Application for Applied AI Engineer at Future - Greenhouse", "https://example.org/x/jobs/1")
    )
    assert gh.company == "Future"
    careers = normalizer.normalize(raw("Associate AI Engineer | Ecolab Careers", "https://jobs.ecolab.com/job/R1/x"))
    assert careers.company == "Ecolab"


def test_title_dash_company_without_ats():
    job = normalizer.normalize(raw("Data Engineer - Zeta Corp", "https://zeta.example/careers/data-engineer"))
    assert (job.title, job.company) == ("Data Engineer", "Zeta Corp")


def test_remote_scope_word_boundaries():
    # "business" and "status" must not be read as "US".
    job = normalizer.normalize(
        raw("Engineer - X", "https://x.example/jobs/1", "Remote role supporting business status dashboards")
    )
    assert job.workplace_type == WorkplaceType.REMOTE
    assert job.remote_scope == RemoteScope.UNKNOWN

    us = normalizer.normalize(raw("Engineer - X", "https://x.example/jobs/2", "Remote (United States only)"))
    assert us.remote_scope == RemoteScope.US_ONLY


def test_skills_experience_and_visa_extracted():
    job = normalizer.normalize(
        raw(
            "ML Engineer - Y",
            "https://y.example/jobs/3",
            "3-5 years of experience with Python, PyTorch and Kubernetes. Visa sponsorship is available. Hybrid.",
        )
    )
    assert {"Python", "PyTorch", "Kubernetes"} <= set(job.required_skills)
    assert job.experience_required == 3
    assert job.workplace_type == WorkplaceType.HYBRID
    assert job.visa_sponsorship.status == VisaSponsorshipStatus.YES


def test_job_id_is_stable_across_query_strings():
    a = normalizer.normalize(raw("A - B", "https://b.example/jobs/9?utm_source=x"))
    b = normalizer.normalize(raw("A - B", "https://b.example/jobs/9"))
    assert a.id == b.id


def test_deduplication_by_id_and_fuzzy_title():
    jobs = [
        normalizer.normalize(raw("Backend Engineer - Acme", "https://acme.example/jobs/1")),
        normalizer.normalize(raw("Backend Engineer - Acme", "https://acme.example/jobs/1?ref=2")),
        normalizer.normalize(raw("Backend Engineer - Acme", "https://boards.example/acme/jobs/77")),
        normalizer.normalize(raw("Frontend Engineer - Acme", "https://acme.example/jobs/2")),
    ]
    assert [j.title for j in JobDeduplicationService().deduplicate(jobs)] == ["Backend Engineer", "Frontend Engineer"]


def test_ats_detection_and_apply_urls():
    assert not detect_ats("https://job-boards.greenhouse.io/emergentlabsinc").is_posting  # board index
    assert detect_ats("https://www.linkedin.com/jobs/search?q=x").name == "aggregator"
    lever = "https://jobs.lever.co/acme/0b9f5c1e-1111-2222-3333-444455556666"
    assert apply_page_url(lever) == lever + "/apply"
    ashby = "https://jobs.ashbyhq.com/acme/0b9f5c1e-1111-2222-3333-444455556666"
    assert apply_page_url(ashby) == ashby + "/application"
