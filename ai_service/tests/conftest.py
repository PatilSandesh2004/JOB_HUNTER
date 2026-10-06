"""Test configuration. Environment is set before any app module reads settings."""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="jobpilot-tests-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}",
        "DATA_DIR": str(_TMP),
        "GROQ_API_KEY": "",  # tests never call the real LLM
        "NOTIFICATION_WEBHOOK_URL": "",
        "BROWSER_HEADLESS": "true",
    }
)

import pytest  # noqa: E402

from ai_service.app.schemas.candidate import CandidatePreferences, CandidateProfile  # noqa: E402


@pytest.fixture
def candidate() -> CandidateProfile:
    return CandidateProfile(
        id="cand-1",
        name="Asha Rao",
        email="asha@example.com",
        phone="+91 98765 43210",
        location="Bengaluru, India",
        current_role="Backend Engineer",
        years_of_experience=4,
        linkedin_url="https://linkedin.com/in/asha-rao",
        skills=["Python", "FastAPI", "PostgreSQL", "Docker", "LangGraph"],
        preferences=CandidatePreferences(
            preferred_roles=["AI Engineer", "Backend Engineer"],
            preferred_locations=["Bengaluru", "Remote"],
            visa_sponsorship_required=False,
        ),
    )
