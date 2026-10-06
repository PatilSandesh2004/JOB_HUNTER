"""Cover letter generation grounded strictly in the candidate's real profile."""

import logging

from ai_service.app.core.errors import LLMUnavailableError
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob

logger = logging.getLogger("jobpilot.tailoring")

_SYSTEM = (
    "You write concise, specific cover letters. Use only facts present in the candidate profile; never "
    "invent employers, metrics, degrees or skills. No placeholders like [Company]. Plain text, no markdown."
)
_USER = """Write a cover letter (3 short paragraphs, under 230 words) for this application.

CANDIDATE
Name: {name}
Current role: {role}
Years of experience: {years}
Skills: {skills}
Recent experience:
{experience}
Summary: {summary}

JOB
Title: {title}
Company: {company}
Skills the posting mentions that the candidate has: {matched}
Posting text:
{description}

Open with "Dear Hiring Team," and end with "Sincerely,\\n{name}"."""


class ApplicationTailoringService:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def generate_cover_letter(
        self, candidate: CandidateProfile, job: NormalizedJob, matched_skills: list[str] | None = None
    ) -> tuple[str, str]:
        """Return (cover_letter, source) where source is 'llm' or 'template'."""
        try:
            letter = await self.llm.complete(_SYSTEM, self._prompt(candidate, job, matched_skills or []))
            return letter.strip(), "llm"
        except LLMUnavailableError as exc:
            logger.warning("Cover letter LLM unavailable, using template: %s", exc)
            return self.template_letter(candidate, job, matched_skills or []), "template"

    @staticmethod
    def _prompt(candidate: CandidateProfile, job: NormalizedJob, matched: list[str]) -> str:
        experience = "\n".join(
            f"- {w.title} at {w.company} ({w.start_date or '?'} - {w.end_date or 'present'})"
            for w in candidate.work_experience[:4]
        )
        return _USER.format(
            name=candidate.name or "the candidate",
            role=candidate.current_role or "not stated",
            years=f"{candidate.years_of_experience:g}" if candidate.years_of_experience else "not stated",
            skills=", ".join(candidate.skills[:25]) or "not stated",
            experience=experience or "- not stated",
            summary=candidate.summary or "not stated",
            title=job.title,
            company=job.company,
            matched=", ".join(matched) or "none identified",
            description=(job.description or "not available")[:3000],
        )

    @staticmethod
    def template_letter(candidate: CandidateProfile, job: NormalizedJob, matched: list[str]) -> str:
        skills = ", ".join((matched or candidate.skills)[:5])
        background = (
            f"As a {candidate.current_role} with {candidate.years_of_experience:g} years of experience"
            if candidate.current_role and candidate.years_of_experience
            else "With my background"
        )
        skill_line = f", including hands-on work with {skills}," if skills else ""
        return (
            "Dear Hiring Team,\n\n"
            f"I am writing to apply for the {job.title} position at {job.company}.\n\n"
            f"{background}{skill_line} I believe I can contribute to your team from day one.\n\n"
            "I would welcome the opportunity to discuss how my experience fits your needs. "
            "Thank you for your time and consideration.\n\n"
            f"Sincerely,\n{candidate.name}"
        )
