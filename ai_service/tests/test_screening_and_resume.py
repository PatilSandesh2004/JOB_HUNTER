"""Answer bank matching, AI answer suggestions, resume tailoring and PDF rendering, ATS detection."""

import pytest

from ai_service.app.integrations.browser.pdf_renderer import render_pdf
from ai_service.app.schemas.candidate import EducationItem, WorkExperience
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.services.jobs.ats import apply_page_url, detect_ats
from ai_service.app.services.resume.resume_tailor import ResumeTailor
from ai_service.app.services.screening.answer_bank import (
    AnswerBook,
    ScreeningSuggester,
    choose_option,
    normalize_question,
)


@pytest.mark.parametrize(
    ("question", "key"),
    [
        ("Are you legally authorized to work in India? *", "are you legally authorized to work in india"),
        ("How did you hear about us?  (required)", "how did you hear about us"),
        ("Years of C++ / C# experience", "years of c++ c# experience"),
    ],
)
def test_normalize_question(question, key):
    assert normalize_question(question) == key


@pytest.mark.parametrize(
    ("options", "value", "expected"),
    [
        (["Select...", "Yes", "No"], "No", "No"),
        (["Yes", "No", "Not applicable"], "no", "No"),  # 'No' must not pick 'Not applicable'
        (["Select...", "Yes, I will require sponsorship", "No, I will not"], "Yes", "Yes, I will require sponsorship"),
        (["No, I won't", "No preference"], "No", None),  # ambiguous: leave it for the human
        (["LinkedIn", "Referral", "Job board"], "job board", "Job board"),
        (["Select...", "Yes", "No"], "Maybe", None),
        (["Select..."], "Select...", None),  # placeholders are never chosen
    ],
)
def test_choose_option(options, value, expected):
    assert choose_option(options, value) == expected


def test_answer_book_sources():
    book = AnswerBook(saved={normalize_question("Are you authorized to work in the US?"): "Yes"})
    assert book.answer_for("Are you authorized to work in the US? *", "radio", ["Yes", "No"]) == "Yes"
    # Exact matching only: one different word is a different question.
    assert book.answer_for("Are you authorized to work in the UK?", "radio", ["Yes", "No"]) is None
    # Voluntary demographic questions are declined, but only when a decline option exists.
    options = ["Male", "Female", "I don't wish to answer"]
    assert book.answer_for("Gender", "select", options) == "I don't wish to answer"
    assert book.answer_for("Gender", "select", ["Male", "Female"]) is None
    assert book.answer_for("Gender", "text", options) is None
    # Relocation is answered only when the profile says so.
    assert book.answer_for("Are you willing to relocate?", "radio", ["Yes", "No"]) is None
    willing = AnswerBook(willing_to_relocate=True)
    assert willing.answer_for("Are you willing to relocate?", "radio", ["Yes", "No"]) == "Yes"


class _FakeLLM:
    available = True

    def __init__(self, reply: dict) -> None:
        self.reply, self.prompts = reply, []

    async def complete_json(self, system, user, **kwargs):
        self.prompts.append(user)
        return self.reply


async def test_suggester_validates_model_output(candidate):
    job = NormalizedJob(id="j", title="AI Engineer", company="Acme", application_url="https://x.test/jobs/1")
    questions = [
        {"label": "Why Acme?", "kind": "textarea", "options": []},
        {"label": "Authorized to work in India?", "kind": "radio", "options": ["Yes", "No"]},
        {"label": "Preferred shift?", "kind": "select", "options": ["Day", "Night"]},
        {"label": "Security clearance?", "kind": "text", "options": []},
    ]
    llm = _FakeLLM(
        {
            "answers": [
                {"id": 0, "answer": "I build LLM agents in Python, which is what this role needs."},
                {"id": 1, "answer": "yes"},
                {"id": 2, "answer": "Evening"},  # not an option: dropped
                {"id": 3, "answer": None},  # profile does not say: no suggestion
                {"id": 9, "answer": "out of range"},
            ]
        }
    )
    suggestions = await ScreeningSuggester(llm).suggest(questions, candidate, job)
    assert suggestions == {
        "Why Acme?": "I build LLM agents in Python, which is what this role needs.",
        "Authorized to work in India?": "Yes",
    }
    assert "Asha Rao" in llm.prompts[0] and "Requires visa sponsorship: no" in llm.prompts[0]


async def test_suggester_without_llm_suggests_nothing(candidate):
    class Offline:
        available = False

    job = NormalizedJob(id="j", title="T", company="C", application_url="https://x.test/jobs/1")
    assert await ScreeningSuggester(Offline()).suggest([{"label": "Q", "kind": "text"}], candidate, job) == {}


def _tailoring_profile(candidate):
    candidate.summary = "Backend engineer <script>alert(1)</script> building APIs."
    candidate.work_experience = [
        WorkExperience(
            company="Acme Corp",
            title="Backend Engineer",
            start_date="Jan 2020",
            description="Led the billing migration.\n• Built FastAPI services on PostgreSQL.\n• Mentored two interns.",
        )
    ]
    candidate.education = [EducationItem(institution="IIT Madras", degree="B.Tech", graduation_year=2019)]
    return candidate


def test_resume_tailor_reorders_and_reports_without_inventing(candidate):
    candidate = _tailoring_profile(candidate)
    job = NormalizedJob(
        id="j",
        title="Backend Engineer",
        company="Beta",
        application_url="https://x.test/jobs/1",
        required_skills=["PostgreSQL", "FastAPI", "Kubernetes"],
    )
    tailor = ResumeTailor()
    report = tailor.report(candidate, job)
    assert report["matched_skills"] == ["PostgreSQL", "FastAPI"]
    assert report["missing_skills"] == ["Kubernetes"]
    assert report["keyword_coverage"] == pytest.approx(66.7)
    assert report["emphasised_bullets"] == 1

    built = tailor.build(candidate, job)
    page = built.html
    # The relevant bullet leads, every bullet is kept verbatim, and nothing absent from the profile appears.
    assert page.index("Built <strong>FastAPI</strong> services") < page.index("Led the billing migration.")
    assert "Mentored two interns." in page
    assert "Kubernetes" not in page
    # Skills that the posting asks for lead the skills line.
    skills_line = page.split("<h2>Skills</h2><p>", 1)[1]
    assert skills_line.startswith("<strong>FastAPI</strong>, <strong>PostgreSQL</strong>") or skills_line.startswith(
        "<strong>PostgreSQL</strong>, <strong>FastAPI</strong>"
    )
    assert "<script>" not in page and "&lt;script&gt;" in page


def test_resume_tailor_needs_some_content(candidate):
    candidate.skills, candidate.work_experience = [], []
    job = NormalizedJob(id="j", title="T", company="C", application_url="https://x.test/jobs/1")
    assert ResumeTailor().build(candidate, job) is None


async def test_render_pdf_with_real_chromium(candidate, tmp_path):
    candidate = _tailoring_profile(candidate)
    job = NormalizedJob(id="j", title="T", company="C", application_url="https://x.test/jobs/1")
    path = await render_pdf(ResumeTailor().build(candidate, job).html, tmp_path / "out" / "resume.pdf")
    assert path.read_bytes().startswith(b"%PDF") and path.stat().st_size > 1000


@pytest.mark.parametrize(
    ("url", "name", "company", "job_id", "apply_url"),
    [
        ("https://acme.recruitee.com/o/backend-engineer", "recruitee", "acme", "backend-engineer", None),
        ("https://acme.teamtailor.com/jobs/123456-ai-engineer", "teamtailor", "acme", "123456", None),
        ("https://acme.bamboohr.com/careers/42", "bamboohr", "acme", "42", None),
        ("https://acme.jobs.personio.de/job/998877?language=en", "personio", "acme", "998877", None),
        ("https://acme.jobs.personio.com/job/5", "personio", "acme", "5", None),
        (
            "https://jobs.lever.co/acme/0b9f5c1e-1111-2222-3333-444455556666",
            "lever",
            "acme",
            "0b9f5c1e-1111-2222-3333-444455556666",
            "https://jobs.lever.co/acme/0b9f5c1e-1111-2222-3333-444455556666/apply",
        ),
    ],
)
def test_detects_more_ats_platforms(url, name, company, job_id, apply_url):
    info = detect_ats(url)
    assert (info.name, info.company_slug, info.job_id) == (name, company, job_id)
    assert info.is_posting and info.auto_apply_supported
    assert apply_page_url(url) == (apply_url or url)


def test_company_board_index_is_not_a_posting():
    info = detect_ats("https://acme.recruitee.com/")
    assert info.name == "recruitee" and not info.is_posting and not info.auto_apply_supported
