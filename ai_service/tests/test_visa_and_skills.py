import pytest

from ai_service.app.schemas.application import ApplicationStatus
from ai_service.app.schemas.job import VisaSponsorshipStatus
from ai_service.app.services.inbox.classifier import classify_email
from ai_service.app.services.skills.catalog import extract_skills, normalize_skill_list
from ai_service.app.services.visa.visa_service import VisaIntelligenceService

visa = VisaIntelligenceService()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("We do not offer visa sponsorship for this role.", VisaSponsorshipStatus.NO),
        ("Candidates must be authorized to work in the US without sponsorship.", VisaSponsorshipStatus.NO),
        ("Unfortunately we are unable to sponsor H1B visas.", VisaSponsorshipStatus.NO),
        ("Visa sponsorship is available for exceptional candidates.", VisaSponsorshipStatus.YES),
        ("We offer relocation and visa support.", VisaSponsorshipStatus.YES),
        ("We are happy to sponsor work visas.", VisaSponsorshipStatus.YES),
        ("Great team, competitive salary.", VisaSponsorshipStatus.UNKNOWN),
    ],
)
def test_visa_detection(text, expected):
    result = visa.evaluate_sponsorship(text)
    assert result.status == expected
    assert (result.evidence is not None) == (expected != VisaSponsorshipStatus.UNKNOWN)


def test_skill_extraction_avoids_substring_false_positives():
    skills = extract_skills("Experience with MySQL and PostgreSQL. The rest of the team uses JavaScript.")
    assert "MySQL" in skills and "PostgreSQL" in skills and "JavaScript" in skills
    assert "SQL" not in skills  # only inside mysql/postgresql
    assert "Java" not in skills
    assert "REST APIs" not in skills


def test_skill_canonicalisation():
    assert normalize_skill_list(["postgres", "K8s", "golang", "Custom Thing"]) == [
        "PostgreSQL",
        "Kubernetes",
        "Go",
        "Custom Thing",
    ]


def test_email_tracker_rejection_beats_interview_words():
    result = classify_email("Your application", "Unfortunately we will not be moving forward to the interview stage.")
    assert result.status == ApplicationStatus.REJECTED
    assert classify_email("Next steps", "We'd like to schedule an interview").status == ApplicationStatus.INTERVIEW
