from ai_service.app.schemas.candidate import RemotePreference
from ai_service.app.schemas.job import (
    NormalizedJob,
    RemoteScope,
    VisaSponsorshipEvidence,
    VisaSponsorshipStatus,
    WorkplaceType,
)
from ai_service.app.services.matching.matching_engine import MatchingEngineService

engine = MatchingEngineService()


def make_job(**overrides) -> NormalizedJob:
    data = {
        "id": "j1",
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Bengaluru",
        "workplace_type": WorkplaceType.ONSITE,
        "required_skills": ["Python", "FastAPI", "Kubernetes"],
        "experience_required": 3,
        "application_url": "https://acme.example/jobs/1",
    }
    return NormalizedJob(**(data | overrides))


def test_strong_match_scores_high(candidate):
    result = engine.evaluate_match(candidate, make_job())
    assert result.passed_hard_filters
    assert result.matched_skills == ["Python", "FastAPI"]
    assert result.missing_skills == ["Kubernetes"]
    assert result.overall_match >= 80


import pytest  # noqa: E402

from ai_service.app.services.matching.matching_engine import role_similarity  # noqa: E402
from ai_service.app.services.search.search_service import LISTING_TITLE_RE  # noqa: E402


@pytest.mark.parametrize(
    ("target", "title", "low", "high"),
    [
        ("AI Engineer", "Senior AI Engineer", 90, 100),
        ("AI Engineer", "Machine Learning Engineer", 75, 100),
        ("AI Engineer", "Tier III Service Desk Engineer", 0, 30),
        ("Backend Engineer", "Senior Back-end Developer (Python)", 75, 100),
        ("Backend Engineer", "Senior Accountant", 0, 20),
    ],
)
def test_role_similarity(target, title, low, high):
    assert low <= role_similarity(target, title) <= high


@pytest.mark.parametrize(
    ("title", "is_listing"),
    [
        ("Remote AI Engineer Jobs in the US ($64K-$211K)", True),
        ("1,234 Python Developer jobs", True),
        ("Jobs at Acme", True),
        ("Senior AI Engineer - Acme", False),
        ("Job Application for Backend Engineer at Optiver", False),
    ],
)
def test_listing_page_titles(title, is_listing):
    assert bool(LISTING_TITLE_RE.search(title)) == is_listing


def test_single_skill_snippet_is_not_a_perfect_skill_fit(candidate):
    one = engine.evaluate_match(candidate, make_job(required_skills=["Python"]))
    many = engine.evaluate_match(candidate, make_job(required_skills=["Python", "FastAPI", "PostgreSQL", "Docker"]))
    assert one.skill_match < 80 < many.skill_match


def test_unrelated_title_scores_lower(candidate):
    good = engine.evaluate_match(candidate, make_job())
    bad = engine.evaluate_match(candidate, make_job(title="Senior Accountant", required_skills=["Excel"]))
    assert bad.overall_match < good.overall_match - 30


def test_sponsorship_hard_filter(candidate):
    candidate.preferences.visa_sponsorship_required = True
    job = make_job(visa_sponsorship=VisaSponsorshipEvidence(status=VisaSponsorshipStatus.NO))
    result = engine.evaluate_match(candidate, job)
    assert not result.passed_hard_filters
    assert result.overall_match <= 35


def test_remote_only_preference_rejects_onsite(candidate):
    candidate.preferences.remote_preference = RemotePreference.REMOTE_ONLY
    assert not engine.evaluate_match(candidate, make_job()).passed_hard_filters
    remote = make_job(workplace_type=WorkplaceType.REMOTE, remote_scope=RemoteScope.INDIA_ONLY)
    assert engine.evaluate_match(candidate, remote).location_match == 100


def test_region_restricted_remote_penalised(candidate):
    job = make_job(workplace_type=WorkplaceType.REMOTE, location="Remote - United States")
    assert engine.evaluate_match(candidate, job).location_match == 25
    snippet_only = make_job(workplace_type=WorkplaceType.REMOTE, location="Remote", remote_scope=RemoteScope.US_ONLY)
    assert engine.evaluate_match(candidate, snippet_only).location_match == 25
    foreign_office = make_job(location="Berlin, Germany")
    assert engine.evaluate_match(candidate, foreign_office).location_match == 20
