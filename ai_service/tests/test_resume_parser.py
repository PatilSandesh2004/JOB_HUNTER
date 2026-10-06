import io

import pytest
from docx import Document

from ai_service.app.core.errors import ResumeParseError
from ai_service.app.services.resume.resume_parser import ResumeParserService

RESUME = """ASHA RAO
Bengaluru, India | asha.rao@example.com | +91 98765 43210
linkedin.com/in/asha-rao | github.com/asharao

EXPERIENCE
Backend Engineer, Acme Corp            Jan 2021 - Present
 - Built FastAPI services on PostgreSQL and Docker
Software Engineer, Beta Labs           Jun 2019 - Dec 2020
 - Python data pipelines with Airflow

SKILLS
Python, Go, Kubernetes, LangGraph
"""

parser = ResumeParserService(llm=None)


def test_heuristic_parse_extracts_contact_and_skills():
    profile = parser.parse_heuristic(RESUME)
    assert profile.name == "Asha Rao"
    assert profile.email == "asha.rao@example.com"
    assert profile.phone == "+91 98765 43210"
    assert profile.linkedin_url == "linkedin.com/in/asha-rao"
    assert {"Python", "FastAPI", "PostgreSQL", "Docker", "Kubernetes", "LangGraph", "Airflow"} <= set(profile.skills)


def test_years_computed_from_date_ranges():
    years = parser.parse_heuristic(RESUME).years_of_experience
    assert 6.5 <= years <= 9  # Jun 2019 -> present, overlap-free


def test_nothing_is_invented_for_sparse_resume():
    profile = parser.parse_heuristic("Some text without any contact details at all, really nothing here.")
    assert profile.name == ""
    assert profile.email is None
    assert profile.work_experience == []
    assert profile.education == []


async def test_parse_without_llm_falls_back_to_heuristics():
    profile = await parser.parse(RESUME)
    assert profile.email == "asha.rao@example.com"


def test_docx_extraction():
    document = Document()
    for line in RESUME.splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    text = parser.extract_text(buffer.getvalue(), "resume.docx")
    assert "asha.rao@example.com" in text


def test_rejects_unsupported_and_empty_files():
    with pytest.raises(ResumeParseError):
        parser.extract_text(b"data", "resume.exe")
    with pytest.raises(ResumeParseError):
        parser.extract_text(b"   ", "resume.txt")
