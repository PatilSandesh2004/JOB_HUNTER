"""Check a resume against one job before applying: keyword coverage and how readable it is for an
applicant tracking system (ATS), with concrete, truthful suggestions."""

import hashlib
import logging
import re
from typing import Any

from ai_service.app.core.errors import LLMUnavailableError
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.services.matching.matching_engine import candidate_skill_profile
from ai_service.app.services.matching.roles import parse_title
from ai_service.app.services.skills.catalog import skill_pattern

logger = logging.getLogger("jobpilot.resume_check")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
_LINKEDIN = re.compile(r"linkedin\.com/in/", re.I)
_DATES = re.compile(r"\b(?:19|20)\d{2}\b")
_NUMBERS = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|x\b|k\b|\+|ms\b|users|customers|requests)|\b\d{2,}\b", re.I)
_SECTIONS = {
    "experience": re.compile(r"\b(experience|employment|work history)\b", re.I),
    "education": re.compile(r"\b(education|academic|degree|university|college)\b", re.I),
    "skills": re.compile(r"\b(skills|technologies|tech stack|tools)\b", re.I),
}

_TIPS_SYSTEM = (
    "You are a resume coach. Suggest truthful edits only: reorder, rephrase or surface experience the candidate "
    "already has; never suggest inventing skills or results. Respond with a JSON object only."
)
_TIPS_USER = """Job: {title} at {company}
Required skills: {required}
Posting excerpt: {excerpt}

Resume excerpt:
{resume}

Return {{"tips": [3 short, specific suggestions to tailor this resume to the job]}}"""


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "ok": ok, "detail": detail}


def check_resume(text: str, job: NormalizedJob, candidate: CandidateProfile | None) -> dict[str, Any]:
    required, preferred = job.required_skills, job.preferred_skills
    found = [s for s in required if skill_pattern(s).search(text)]
    found_preferred = [s for s in preferred if skill_pattern(s).search(text)]
    missing = [s for s in required if s not in found]
    missing_preferred = [s for s in preferred if s not in found_preferred]
    known = candidate_skill_profile(candidate.skills)[0] if candidate else set()
    unmentioned = [s for s in missing if s in known]  # you have it, the resume does not say so
    weight = len(required) + 0.5 * len(preferred)
    keyword_coverage = round(100 * (len(found) + 0.5 * len(found_preferred)) / weight, 1) if weight else None

    words = len(text.split())
    sections = [name for name, pattern in _SECTIONS.items() if pattern.search(text)]
    title_words = [w for w in parse_title(job.title).specialties] or [job.title.split()[0].lower()]
    checks = [
        _check(
            "Readable text", len(text) >= 600, f"{len(text)} characters extracted" if text else "No text could be read"
        ),
        _check("Contact details", bool(_EMAIL.search(text) and _PHONE.search(text)), "Email and phone near the top"),
        _check(
            "Standard sections",
            len(sections) == 3,
            f"Found: {', '.join(sections) or 'none'} (want experience, education, skills)",
        ),
        _check("Dates on experience", len(_DATES.findall(text)) >= 2, "Years next to each role"),
        _check("Length", 300 <= words <= 1100, f"{words} words (one to two pages is ideal)"),
        _check("LinkedIn profile", bool(_LINKEDIN.search(text)), "A linkedin.com/in/ link"),
        _check("Quantified results", len(_NUMBERS.findall(text)) >= 3, "Numbers that show impact (%, users, latency)"),
        _check(
            "Job title keywords", any(w in text.lower() for w in title_words), f"Words like {', '.join(title_words)}"
        ),
    ]
    passed = sum(c["ok"] for c in checks)
    readability = round(100 * passed / len(checks), 1)
    score = round(0.6 * keyword_coverage + 0.4 * readability, 1) if keyword_coverage is not None else readability

    suggestions = [
        f"Your profile lists {s}, but this resume never mentions it: add it where you used it." for s in unmentioned
    ]
    suggestions += [
        f"The posting requires {s}. If you have used it, say where; if not, expect to be asked about it."
        for s in missing
        if s not in unmentioned
    ][:4]
    advice = {
        "Contact details": "Put your email and phone number at the top.",
        "Standard sections": "Use plain section headings: Experience, Education, Skills.",
        "Dates on experience": "Add start and end dates (month and year) to every role.",
        "Length": "Aim for one to two pages; cut old or unrelated details.",
        "LinkedIn profile": "Add your LinkedIn URL next to your contact details.",
        "Quantified results": "Add numbers to your achievements (e.g. 'cut latency 40%', 'served 2M users').",
        "Readable text": "Export the resume as a text-based PDF or DOCX (not a scanned image).",
        "Job title keywords": f"Mention the kind of role you are applying for ('{job.title}') in your summary.",
    }
    suggestions += [advice[c["check"]] for c in checks if not c["ok"]]
    return {
        "score": score,
        "keyword_coverage": keyword_coverage,
        "readability": readability,
        "matched_skills": found + found_preferred,
        "missing_skills": missing,
        "missing_preferred": missing_preferred,
        "in_profile_not_in_resume": unmentioned,
        "checks": checks,
        "suggestions": suggestions,
        "tips": [],
    }


class ResumeCheckService:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self._tips: dict[str, list[str]] = {}

    async def check(self, text: str, job: NormalizedJob, candidate: CandidateProfile | None, label: str) -> dict:
        result = check_resume(text, job, candidate) | {"resume": label}
        if not self.llm.available or not text:
            return result
        key = hashlib.sha256(f"{job.id}|{text}".encode()).hexdigest()
        if key not in self._tips:
            prompt = _TIPS_USER.format(
                title=job.title,
                company=job.company,
                required=", ".join(job.required_skills) or "not listed",
                excerpt=(job.description or "")[:1500],
                resume=text[:3000],
            )
            try:
                data = await self.llm.complete_json(_TIPS_SYSTEM, prompt, temperature=0.3, max_tokens=700)
                self._tips[key] = [str(t).strip() for t in data.get("tips") or [] if str(t).strip()][:3]
            except LLMUnavailableError as exc:
                logger.info("Resume tips unavailable: %s", exc)
                return result
        return result | {"tips": self._tips[key]}
