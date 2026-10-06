"""Answers to application-form screening questions.

Three sources, in order:
1. Your answer bank: answers you wrote or approved, matched on the normalised question text. Matching is
   exact on purpose: "authorised to work in the US?" and "... in the UK?" differ by one word.
2. Safe built-ins: decline-to-answer for voluntary demographic (EEO) questions, and "Yes" to relocation
   only when your profile says you are willing to relocate.
3. AI suggestions for what is left, drafted only from facts in your profile and always shown to you for
   review. They are never used to fill a form until you save them to the answer bank.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from ai_service.app.core.errors import LLMUnavailableError
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob

logger = logging.getLogger("jobpilot.screening")

CHOICE_KINDS = frozenset({"select", "radio"})
_NOISE_RE = re.compile(r"\(required\)|\(optional\)|\*", re.I)
_PLACEHOLDER_RE = re.compile(r"^\s*$|^(select|choose|please select|pick)\b|^[-—–\s.]+$", re.I)
_EEO_RE = re.compile(
    r"\bgender\b|\brace\b|ethnic|hispanic|latin[oax]|veteran|disabilit|sexual orientation|transgender|pronoun", re.I
)
_DECLINE_RE = re.compile(
    r"decline|prefer not|rather not|choose not|do not wish|don.?t wish|not wish to|"
    r"not to (say|disclose|answer|self.?identify)",
    re.I,
)
_RELOCATE_RE = re.compile(r"\brelocat", re.I)


def normalize_question(text: str) -> str:
    """Lower-case words and numbers only, without 'required' markers: the answer-bank lookup key."""
    cleaned = re.sub(r"[^a-z0-9+#]+", " ", _NOISE_RE.sub(" ", (text or "").lower()))
    return " ".join(cleaned.split())[:300]


def real_options(options: list[str]) -> list[str]:
    """Drop placeholders such as 'Select...' from a select/radio option list."""
    return [o for o in options if not _PLACEHOLDER_RE.search(o)]


def choose_option(options: list[str], value: str) -> str | None:
    """The option that unambiguously matches `value`, or None. 'No' never matches 'Not applicable'."""
    wanted = normalize_question(value)
    if not wanted:
        return None
    normalized = {option: normalize_question(option) for option in real_options(options)}
    for matcher in (
        lambda n: n == wanted,
        lambda n: n.split()[:1] == wanted.split()[:1] and len(wanted.split()) == 1,
        lambda n: f" {wanted} " in f" {n} ",
    ):
        hits = [option for option, n in normalized.items() if matcher(n)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return None
    return None


@dataclass
class AnswerBook:
    """Everything the form filler may use to answer non-contact questions. Plain data (crosses threads)."""

    saved: dict[str, str] = field(default_factory=dict)  # normalize_question(question) -> answer
    willing_to_relocate: bool = False

    def answer_for(self, question: str, kind: str, options: list[str]) -> str | None:
        key = normalize_question(question)
        if not key:
            return None
        if key in self.saved:
            return self.saved[key]
        if kind in CHOICE_KINDS and _EEO_RE.search(question):
            return next((o for o in real_options(options) if _DECLINE_RE.search(o)), None)
        if self.willing_to_relocate and _RELOCATE_RE.search(question):
            return "Yes"
        return None


_SUGGEST_SYSTEM = (
    "You help a job applicant answer application-form questions. Use ONLY facts stated in the candidate "
    "profile. If the profile does not answer a question, return null for it: never guess, never invent "
    "employers, dates, numbers, legal status or personal details. For questions with options, answer with "
    "one option copied exactly. Keep free-text answers under 80 words, first person, plain text. "
    "Respond with a JSON object only."
)
_SUGGEST_USER = """CANDIDATE PROFILE
{profile}

JOB: {title} at {company}

QUESTIONS
{questions}

Return {{"answers": [{{"id": <question id>, "answer": <string or null>}}, ...]}} with one entry per question."""


class ScreeningSuggester:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def suggest(self, questions: list[dict], candidate: CandidateProfile, job: NormalizedJob) -> dict[str, str]:
        """Map question label -> suggested answer, for the questions the profile can answer."""
        if not questions or not self.llm.available:
            return {}
        listed = [
            {"id": i, "question": q["label"], **({"options": real_options(q["options"])} if q.get("options") else {})}
            for i, q in enumerate(questions)
        ]
        try:
            data = await self.llm.complete_json(
                _SUGGEST_SYSTEM,
                _SUGGEST_USER.format(
                    profile=_profile_facts(candidate),
                    title=job.title,
                    company=job.company,
                    questions=json.dumps(listed, ensure_ascii=False, indent=1),
                ),
                temperature=0.1,
                max_tokens=1500,
            )
        except LLMUnavailableError as exc:
            logger.warning("Screening suggestions skipped: %s", exc)
            return {}
        suggestions: dict[str, str] = {}
        for item in data.get("answers") or []:
            if not isinstance(item, dict) or not isinstance(item.get("answer"), str):
                continue
            index = item.get("id")
            if not isinstance(index, int) or not 0 <= index < len(questions):
                continue
            question, answer = questions[index], item["answer"].strip()
            if question.get("kind") in CHOICE_KINDS:
                answer = choose_option(question.get("options") or [], answer) or ""
            if answer:
                suggestions[question["label"]] = answer[:1000]
        return suggestions


def _profile_facts(candidate: CandidateProfile) -> str:
    prefs = candidate.preferences
    lines = [
        f"Name: {candidate.name}",
        f"Location: {candidate.location or 'not stated'}",
        f"Current role: {candidate.current_role or 'not stated'} at {candidate.current_company or 'not stated'}",
        f"Years of experience: {candidate.years_of_experience:g}" if candidate.years_of_experience else "",
        f"Skills: {', '.join(candidate.skills[:30])}" if candidate.skills else "",
        *(
            f"Experience: {w.title} at {w.company} ({w.start_date or '?'} - {w.end_date or 'present'})"
            for w in candidate.work_experience[:5]
        ),
        *(
            f"Education: {e.degree or ''} {e.field_of_study or ''} at {e.institution} {e.graduation_year or ''}".strip()
            for e in candidate.education[:3]
        ),
        f"Requires visa sponsorship: {'yes' if prefs.visa_sponsorship_required else 'no'}",
        f"Willing to relocate: {'yes' if prefs.willing_to_relocate else 'not stated'}",
        f"Work arrangement preference: {prefs.remote_preference.value}",
        f"Expected salary: {prefs.expected_salary}" if prefs.expected_salary else "",
        f"Notice period / start: {prefs.notice_period}" if prefs.notice_period else "",
        f"LinkedIn: {candidate.linkedin_url}" if candidate.linkedin_url else "",
        f"Summary: {candidate.summary}" if candidate.summary else "",
    ]
    return "\n".join(line for line in lines if line)
