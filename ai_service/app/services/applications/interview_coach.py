"""Mock interview for one application: questions one at a time, short feedback on each answer, a summary.

With an LLM the interviewer adapts to the job and your answers; without one it asks prepared questions from
the posting's skills and common behavioural questions, without feedback.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.core.errors import LLMUnavailableError, NotFoundError
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.models.application import ApplicationModel
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.services.applications.insights_service import fallback_insights

logger = logging.getLogger("jobpilot.interview")

QUESTIONS = 5
MAX_MESSAGES = 40

_SYSTEM = """You are a friendly but rigorous interviewer for the role "{title}" at {company}.
The candidate: {role}, {years} years of experience; skills: {skills}.
Job description excerpt: {excerpt}

Run a mock interview of {n} questions, one at a time, mixing technical questions about the job's skills with
behavioural ones. After each candidate answer give feedback in at most two sentences (one strength, one thing to
improve), then ask the next question. After the last answer, give a short overall assessment.
Respond with a JSON object only: {{"feedback": "<feedback on the last answer, empty on the first turn>",
"question": "<the next question, empty when the interview is over>",
"summary": "<only when over: a score out of 10 and the three things to practise>"}}"""


def _prepared_questions(candidate: CandidateProfile, job: NormalizedJob) -> list[str]:
    prep = fallback_insights(candidate, job)
    technical = [
        f"How have you used {topic} in a real project, and what trade-offs did you make?"
        for topic in prep["technical_topics"][:3]
    ]
    questions = [f"Tell me about yourself and why the {job.title} role at {job.company} interests you.", *technical]
    questions += prep["behavioral_questions"]
    return list(dict.fromkeys(questions))[:QUESTIONS]


class InterviewCoach:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def turn(self, session: AsyncSession, application_id: str, messages: list[dict[str, str]]) -> dict:
        """messages: [{"role": "interviewer" | "candidate", "content": ...}] so far. Returns the next turn."""
        app = await session.get(ApplicationModel, application_id)
        if app is None:
            raise NotFoundError("Application not found")
        job = await JobRepository(session).get(app.job_id)
        candidate = await CandidateRepository(session).get_active()
        if job is None or candidate is None:
            raise NotFoundError("The job or your profile is missing")
        history = [m for m in messages if m.get("role") in ("interviewer", "candidate") and m.get("content")][
            -MAX_MESSAGES:
        ]
        asked = sum(m["role"] == "interviewer" for m in history)
        if self.llm.available:
            try:
                return await self._llm_turn(candidate, job, history, asked)
            except LLMUnavailableError as exc:
                logger.warning("Mock interview fell back to prepared questions: %s", exc)
        questions = _prepared_questions(candidate, job)
        if asked >= len(questions):
            return {
                "feedback": "",
                "question": "",
                "summary": "That's all the prepared questions. Well done!",
                "done": True,
                "source": "template",
            }
        return {"feedback": "", "question": questions[asked], "summary": "", "done": False, "source": "template"}

    async def _llm_turn(self, candidate: CandidateProfile, job: NormalizedJob, history: list[dict], asked: int) -> dict:
        system = _SYSTEM.format(
            title=job.title,
            company=job.company,
            role=candidate.current_role or "candidate",
            years=f"{candidate.years_of_experience:g}",
            skills=", ".join(candidate.skills[:20]) or "not stated",
            excerpt=(job.description or "")[:1500],
            n=QUESTIONS,
        )
        transcript = (
            "\n".join(f"{m['role'].upper()}: {m['content'][:1500]}" for m in history)
            or "(the interview has not started)"
        )
        status = "Ask the first question." if not history else (
            "That was the last answer: give feedback and the summary, no new question." if asked >= QUESTIONS else
            f"Question {asked + 1} of {QUESTIONS} is next."
        )  # fmt: skip
        data = await self.llm.complete_json(
            system, f"Transcript so far:\n{transcript}\n\n{status}", temperature=0.5, max_tokens=900
        )
        question = str(data.get("question") or "").strip() if asked < QUESTIONS else ""
        summary = str(data.get("summary") or "").strip()
        return {
            "feedback": str(data.get("feedback") or "").strip(),
            "question": question,
            "summary": summary,
            "done": not question,
            "source": "llm",
        }
