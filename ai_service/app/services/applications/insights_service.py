"""Interview preparation for one application: skill gaps, topics to revise, behavioural questions."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.core.errors import LLMUnavailableError, NotFoundError
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.models.application import ApplicationModel
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.services.skills.catalog import normalize_skill_list

logger = logging.getLogger("jobpilot.insights")

KEYS = ("missing_skills", "technical_topics", "behavioral_questions")
MAX_ITEMS = 5

_SYSTEM = (
    "You are an experienced technical recruiter and interview coach. Base everything on the job description "
    "and the candidate profile given. Respond with a JSON object only."
)
_USER = """Prepare this candidate for an interview.

Job: {title} at {company}
Description:
{description}

Candidate: {years} years of experience, current role {role}.
Summary: {summary}
Skills: {skills}

Return JSON with keys (each a list of at most {n} short strings):
- "missing_skills": skills or experience the job asks for that the candidate's profile does not show
- "technical_topics": concepts to revise for this interview, most important first
- "behavioral_questions": questions this company is likely to ask, given the role"""

_GENERIC_QUESTIONS = [
    "Tell me about a project you are proud of and your exact contribution.",
    "Describe a time you disagreed with a teammate. How did you resolve it?",
    "Tell me about a bug or outage you caused or fixed. What did you learn?",
    "Why do you want to work at {company}, and why this role?",
    "Describe a time you had to learn a new technology quickly.",
]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:MAX_ITEMS]


def fallback_insights(candidate: CandidateProfile, job: NormalizedJob) -> dict[str, list[str]]:
    """Without an LLM: gaps and topics from the posting's recognised skills, plus common questions."""
    have = {s.lower() for s in normalize_skill_list(candidate.skills)}
    asked = [*job.required_skills, *getattr(job, "preferred_skills", [])]
    missing = [s for s in dict.fromkeys(asked) if s.lower() not in have]
    return {
        "missing_skills": missing[:MAX_ITEMS],
        "technical_topics": list(dict.fromkeys(job.required_skills))[:MAX_ITEMS],
        "behavioral_questions": [q.format(company=job.company) for q in _GENERIC_QUESTIONS][:MAX_ITEMS],
        "source": "template",
    }


class ApplicationInsightsService:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def generate(self, session: AsyncSession, application_id: str) -> dict:
        app = await session.get(ApplicationModel, application_id)
        if app is None:
            raise NotFoundError("Application not found")
        job = await JobRepository(session).get(app.job_id)
        if job is None:
            raise NotFoundError("The job for this application no longer exists")
        candidate = await CandidateRepository(session).get_active()
        if candidate is None:
            raise NotFoundError("Create your profile first")
        if not self.llm.available:
            return fallback_insights(candidate, job)
        prompt = _USER.format(
            title=job.title,
            company=job.company,
            description=(job.description or "Not available")[:6000],
            years=f"{candidate.years_of_experience:g}",
            role=candidate.current_role or "not stated",
            summary=candidate.summary or "not stated",
            skills=", ".join(candidate.skills[:40]) or "not stated",
            n=MAX_ITEMS,
        )
        try:
            data = await self.llm.complete_json(_SYSTEM, prompt, temperature=0.3, max_tokens=1500)
        except LLMUnavailableError as exc:
            logger.warning("Interview prep fell back to a template: %s", exc)
            return fallback_insights(candidate, job)
        insights = {key: _string_list(data.get(key)) for key in KEYS}
        if not any(insights.values()):
            return fallback_insights(candidate, job)
        return insights | {"source": "llm"}
