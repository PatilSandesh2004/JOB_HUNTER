"""Short, personal outreach notes asking a contact for a chat or a referral."""

import logging

from ai_service.app.core.errors import LLMUnavailableError
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.schemas.candidate import CandidateProfile

logger = logging.getLogger("jobpilot.outreach")

LINKEDIN_NOTE_LIMIT = 300  # LinkedIn's limit for a connection-request note

_SYSTEM = (
    "You write short, specific, polite networking messages for job seekers. Use only the facts given; "
    "never invent achievements, mutual connections or numbers. Respond with a JSON object only."
)
_USER = """Write outreach messages from {name} to {contact} ({contact_role}) at {company}, about the role "{job_title}".

About {name}: {role}, {years} years of experience. Strongest skills: {skills}.

Return JSON with keys:
- "linkedin_note": a LinkedIn connection note, at most 280 characters, no greeting line breaks.
- "email_message": a direct message of at most 150 words asking for a short chat or a referral."""


def _template(candidate: CandidateProfile | None, contact: str, company: str, job_title: str) -> dict[str, str]:
    name = candidate.name if candidate and candidate.name else "I"
    skills = ", ".join((candidate.skills if candidate else [])[:3])
    background = f" with experience in {skills}" if skills else ""
    first = contact.split()[0] if contact else "there"
    note = (
        f"Hi {first}, I'm interested in the {job_title} role at {company}. I'm a {_role(candidate)}{background}. "
        "Would you be open to a quick chat?"
    )
    email = (
        f"Hi {first},\n\nI came across the {job_title} opening at {company} and it looks like a strong fit for my "
        f"background as a {_role(candidate)}{background}. Would you have 15 minutes for a quick chat about the team, "
        "or be open to referring me if you think I'd be a fit?\n\nThank you for your time,\n"
        f"{name if name != 'I' else ''}"
    )
    return {"linkedin_note": note[:LINKEDIN_NOTE_LIMIT], "email_message": email.strip(), "source": "template"}


def _role(candidate: CandidateProfile | None) -> str:
    return (candidate.current_role if candidate and candidate.current_role else "software professional").strip()


class OutreachWriter:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def draft(
        self,
        candidate: CandidateProfile | None,
        company: str,
        contact_name: str,
        contact_role: str,
        job_title: str,
    ) -> dict[str, str]:
        if not self.llm.available or candidate is None:
            return _template(candidate, contact_name, company, job_title)
        prompt = _USER.format(
            name=candidate.name or "the candidate",
            contact=contact_name or "the hiring team",
            contact_role=contact_role or "employee",
            company=company,
            job_title=job_title,
            role=_role(candidate),
            years=f"{candidate.years_of_experience:g}",
            skills=", ".join(candidate.skills[:8]) or "not stated",
        )
        try:
            data = await self.llm.complete_json(_SYSTEM, prompt, temperature=0.5, max_tokens=900)
        except LLMUnavailableError as exc:
            logger.warning("Outreach drafting fell back to a template: %s", exc)
            return _template(candidate, contact_name, company, job_title)
        note = str(data.get("linkedin_note") or "").strip()
        email = str(data.get("email_message") or "").strip()
        if not note or not email:
            return _template(candidate, contact_name, company, job_title)
        return {"linkedin_note": note[:LINKEDIN_NOTE_LIMIT], "email_message": email, "source": "llm"}
