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
        "SEMANTIC_MATCHING": "false",  # no model download in tests
    }
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from ai_service.app.agents.application_agent.graph import ApplicationAgent  # noqa: E402
from ai_service.app.agents.search_agent.graph import SearchAgent  # noqa: E402
from ai_service.app.api import deps  # noqa: E402
from ai_service.app.database.session import AsyncSessionLocal, Base, init_db  # noqa: E402
from ai_service.app.main import app  # noqa: E402
from ai_service.app.schemas.candidate import CandidatePreferences, CandidateProfile  # noqa: E402
from ai_service.app.services.applications.application_service import ApplicationService  # noqa: E402
from ai_service.app.services.applications.tailoring_service import ApplicationTailoringService  # noqa: E402
from ai_service.app.services.resume.library import ResumeLibrary  # noqa: E402
from ai_service.app.services.resume.resume_parser import ResumeParserService  # noqa: E402
from ai_service.app.services.tasks.runner import TaskRunner  # noqa: E402
from ai_service.tests.fakes import (  # noqa: E402
    FakePdfRenderer,
    FakeSearchService,
    FakeSuggester,
    RecordingFiller,
    offline_llm,
)


async def reset_database() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()


@pytest.fixture
async def client():
    """API client on an empty database, with fake search/LLM/browser and a manually driven task runner."""
    await reset_database()
    filler, renderer, suggester = RecordingFiller(), FakePdfRenderer(), FakeSuggester()
    llm = offline_llm()
    service = ApplicationService(
        AsyncSessionLocal,
        lambda: ApplicationAgent(ApplicationTailoringService(llm), filler=filler, pdf_renderer=renderer),
        suggester=suggester,
        resume_library=ResumeLibrary(ResumeParserService(llm)),
    )
    app.dependency_overrides[deps.get_search_agent] = lambda: SearchAgent(FakeSearchService(), llm)
    app.dependency_overrides[deps.get_application_service] = lambda: service
    app.dependency_overrides[deps.get_resume_parser] = lambda: deps.ResumeParserService(llm)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        c.filler, c.renderer, c.suggester = filler, renderer, suggester
        c.service = service
        # Queued agent work runs when a test calls `await client.runner.run_due_once()`.
        c.runner = TaskRunner(AsyncSessionLocal, service.task_handlers(), backoff_seconds=[0])
        yield c
    app.dependency_overrides.clear()


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
