"""Explainable candidate-to-job scoring.

Title fit uses role understanding (services/matching/roles.py): a sales or writing job with "AI" in its name
is not an AI engineering job, and "Backend Engineer (Python)" is a Python developer job. Skills distinguish
required from nice-to-have, and count your own skills outside the catalogue when the posting names them.
Every score carries a confidence: a posting that says almost nothing cannot be a confident strong match.
"""

import re
from typing import TYPE_CHECKING

from ai_service.app.schemas.candidate import CandidateProfile, RemotePreference
from ai_service.app.schemas.job import NormalizedJob, VisaSponsorshipStatus, WorkplaceType
from ai_service.app.schemas.match import MatchResult
from ai_service.app.services.jobs.location_service import LocationFit, LocationMatcher
from ai_service.app.services.matching.roles import describe, role_similarity
from ai_service.app.services.skills.catalog import canonicalize, extract_skills, in_catalog, skill_pattern

if TYPE_CHECKING:
    from ai_service.app.services.matching.feedback import FeedbackModel

__all__ = [
    "MatchingEngineService",
    "candidate_skill_profile",
    "default_band",
    "experience_band",
    "role_similarity",
    "title_seniority_conflict",
]

WEIGHTS = {"title": 0.25, "skills": 0.35, "experience": 0.15, "location": 0.15, "sponsorship": 0.10}
# With a resume-to-description similarity available, part of the skill weight moves to it.
SEMANTIC_WEIGHTS = {
    "title": 0.24,
    "skills": 0.25,
    "semantic": 0.14,
    "experience": 0.14,
    "location": 0.14,
    "sponsorship": 0.09,
}
NEUTRAL = 60.0  # used when the posting does not give enough information to judge
UNKNOWN_SKILLS = 45.0  # no recognisable skills: below a half match, so known good matches rank first
SKILL_PRIOR = 2  # pseudo-count of "unknown" skills blended into small skill lists
LOW_CONFIDENCE_CAP = 80.0  # a posting that says almost nothing is never announced as a strong match
PREFERRED_WEIGHT = 0.5

_SOFT_SKILLS = {
    "communication", "communication skills", "teamwork", "team player", "leadership", "problem solving",
    "problem-solving", "collaboration", "english", "time management", "critical thinking", "adaptability",
    "presentation", "presentation skills", "analytical skills", "analytical thinking", "attention to detail",
    "interpersonal skills", "self-motivated", "ownership", "mentoring", "creativity", "multitasking",
}  # fmt: skip

_SENIOR_TITLE_RE = re.compile(r"\b(senior|sr\.?|lead|principal|staff|head|manager|director|architect|vp)\b", re.I)
_JUNIOR_TITLE_RE = re.compile(
    r"\b(intern|internship|trainee|fresher|graduate|apprentice|junior|jr\.?|entry[- ]level)\b", re.I
)
_INTERNSHIP_RE = re.compile(r"\b(intern|internship|trainee|apprentice(?:ship)?)\b", re.I)


def experience_band(value: str | None) -> tuple[float, float | None] | None:
    """'2-4' -> (2, 4); '8+' -> (8, None); 'ANY'/junk -> None."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?)|(\+))\s*", value or "")
    if not match:
        return None
    low = float(match.group(1))
    return (low, None) if match.group(3) else (low, float(match.group(2)))


def default_band(years: float | None) -> tuple[float, float | None] | None:
    """The experience range a candidate fits when they did not choose one: a year below to 1.5 above."""
    if not years:
        return None
    return max(0.0, years - 1), years + 1.5


def title_seniority_conflict(
    title: str, band: tuple[float, float | None] | None, candidate_years: float | None = None
) -> str | None:
    """Why a title's seniority clearly contradicts the wanted experience band or candidate years, else None."""
    if band is not None:
        low, high = band
        if high is not None and high <= 4 and _SENIOR_TITLE_RE.search(title):
            return "too senior"
        if low >= 5 and _JUNIOR_TITLE_RE.search(title):
            return "too junior"
    if candidate_years is not None:
        if candidate_years < 3.5 and _SENIOR_TITLE_RE.search(title):
            return "too senior for candidate experience"
        if candidate_years >= 6.0 and _JUNIOR_TITLE_RE.search(title):
            return "too junior for candidate experience"
        if candidate_years >= 1.0 and _INTERNSHIP_RE.search(title):
            return "an internship, and you already have work experience"
    return None


def candidate_skill_profile(skills: list[str]) -> tuple[set[str], list[str]]:
    """(catalogue skills you have, your other skills). Free text like "SQL (PostgreSQL)" or "Hugging Face
    Transformers" counts as the catalogue skills it names; anything else stays as written."""
    known: set[str] = set()
    custom: list[str] = []
    for raw in skills:
        if not raw or not raw.strip():
            continue
        name = canonicalize(raw)
        found = {name} if in_catalog(name) else set(extract_skills(raw))
        if found:
            known |= found
        elif raw.strip().lower() not in _SOFT_SKILLS and len(raw.strip()) >= 2:
            custom.append(raw.strip())
    return known, list(dict.fromkeys(custom))


def _confidence(job: NormalizedJob) -> str:
    info = 0
    description = len(job.description or "")
    info += 2 if description >= 500 else 1 if description >= 150 else 0
    skills = len(job.required_skills) + len(job.preferred_skills)
    info += 2 if skills >= 4 else 1 if skills else 0
    info += 1 if job.experience_required is not None else 0
    info += 1 if job.location and job.location != "Unknown" else 0
    return "HIGH" if info >= 5 else "MEDIUM" if info >= 3 else "LOW"


class MatchingEngineService:
    def evaluate_match(
        self,
        candidate: CandidateProfile,
        job: NormalizedJob,
        experience: str | None = None,
        target_roles: list[str] | None = None,
        semantic: float | None = None,
        feedback: "FeedbackModel | None" = None,
    ) -> MatchResult:
        """Score one job for a candidate.

        `experience`: the search's wanted band (e.g. '2-4'); without it the candidate's own years decide.
        `target_roles`: the roles searched for; without them the profile's target roles and current role.
        `semantic`: resume-to-description similarity (0-100), when available.
        `feedback`: what you hid and applied to, nudging similar jobs down or up.
        """
        reasons: list[str] = []
        title_score = self._title_score(candidate, job, reasons, target_roles)
        skill_score, matched, missing, missing_preferred = self._skill_score(candidate, job, reasons)
        band = experience_band(experience) or default_band(candidate.years_of_experience)
        exp_score = self._experience_score(job, reasons, band, candidate.years_of_experience)
        exp_ok = exp_score > 20.0
        loc_score, loc_ok = self._location_score(candidate, job, reasons)
        sponsor_score, sponsor_ok = self._sponsorship_score(candidate, job, reasons)
        passed = loc_ok and sponsor_ok and exp_ok

        parts = {
            "title": title_score,
            "skills": skill_score,
            "experience": exp_score,
            "location": loc_score,
            "sponsorship": sponsor_score,
        }
        weights = WEIGHTS
        if semantic is not None:
            parts["semantic"] = semantic
            weights = SEMANTIC_WEIGHTS
        overall = sum(parts[key] * weight for key, weight in weights.items())
        # A great fit on skills/location is worthless if the role itself is unrelated.
        overall *= min(1.0, 0.4 + title_score / 100)
        if semantic is not None:
            reasons.append(f"Resume similarity to the description: {semantic:.0f}%")
        if feedback is not None:
            points, why = feedback.adjust(job)
            if points and why:
                overall = max(0.0, min(100.0, overall + points))
                reasons.append(why)
        confidence = _confidence(job)
        if confidence == "LOW" and overall > LOW_CONFIDENCE_CAP:
            overall = LOW_CONFIDENCE_CAP
            reasons.append("The posting gives little detail, so this score is capped until more is known")
        if not passed:
            overall = min(overall, 35.0)

        return MatchResult(
            job_id=job.id,
            overall_match=round(overall, 1),
            title_match=round(title_score, 1),
            skill_match=round(skill_score, 1),
            experience_match=round(exp_score, 1),
            location_match=round(loc_score, 1),
            sponsorship_match=round(sponsor_score, 1),
            semantic_match=round(semantic, 1) if semantic is not None else None,
            matched_skills=matched,
            missing_skills=missing,
            missing_preferred=missing_preferred,
            passed_hard_filters=passed,
            confidence=confidence,
            reasons=reasons,
        )

    @staticmethod
    def _title_score(
        candidate: CandidateProfile, job: NormalizedJob, reasons: list[str], target_roles: list[str] | None
    ) -> float:
        profile_targets = [*candidate.preferences.preferred_roles, candidate.current_role or ""]
        targets = [t for t in (target_roles or profile_targets) if t]
        if not targets:
            return NEUTRAL
        skills = [*job.required_skills, *job.preferred_skills]
        best_target, score = max(((t, role_similarity(t, job.title, skills)) for t in targets), key=lambda p: p[1])
        if score >= 80:
            reasons.append(f"Title matches your target role '{best_target}'")
        elif score >= 55:
            reasons.append(f"Related to '{best_target}' ({describe(job.title)})")
        else:
            reasons.append(f"Different kind of job: {describe(job.title)}")
        return score

    @staticmethod
    def _skill_score(
        candidate: CandidateProfile, job: NormalizedJob, reasons: list[str]
    ) -> tuple[float, list[str], list[str], list[str]]:
        have, custom = candidate_skill_profile(candidate.skills)
        text = job.description or ""
        # Your skills outside the catalogue ("MCP", "Groq") count when the posting names them.
        custom_found = [s for s in custom if text and skill_pattern(s).search(text)]
        required = list(dict.fromkeys([*job.required_skills, *custom_found]))
        preferred = [s for s in job.preferred_skills if s not in required]
        if not required and not preferred:
            reasons.append("The posting lists no recognisable skills; skill fit not scored")
            return UNKNOWN_SKILLS, [], [], []

        matched_required = [s for s in required if s in have or s in custom_found]
        matched_preferred = [s for s in preferred if s in have]
        missing = [s for s in required if s not in matched_required]
        missing_preferred = [s for s in preferred if s not in matched_preferred]
        weight = len(required) + PREFERRED_WEIGHT * len(preferred)
        raw = 100.0 * (len(matched_required) + PREFERRED_WEIGHT * len(matched_preferred)) / weight
        # Short lists say little: shrink toward "unknown" so 1/1 is not a "100% fit".
        confidence = weight / (weight + SKILL_PRIOR)
        score = confidence * raw + (1 - confidence) * UNKNOWN_SKILLS
        detail = f"Matches {len(matched_required)}/{len(required)} required skills"
        if preferred:
            detail += f" and {len(matched_preferred)}/{len(preferred)} nice-to-have"
        reasons.append(detail)
        return score, [*matched_required, *matched_preferred], missing, missing_preferred

    @staticmethod
    def _experience_score(
        job: NormalizedJob,
        reasons: list[str],
        band: tuple[float, float | None] | None,
        candidate_years: float | None,
    ) -> float:
        required, required_max = job.experience_required, job.experience_max
        if band is None:
            return NEUTRAL + 15 if required is None else (100.0 if required <= 1 else NEUTRAL)
        low, high = band
        wanted = f"{low:g}{'+' if high is None else f'-{high:g}'}"
        conflict = title_seniority_conflict(job.title, band, candidate_years)
        if conflict:
            reasons.append(f"Title looks {conflict} (you fit {wanted} years)")
            return 0.0
        if required is None:
            return NEUTRAL + 15
        ceiling = low if high is None else high
        asked = f"{required:g}-{required_max:g}" if required_max is not None else f"{required:g}+"
        if required > ceiling:
            reasons.append(f"Asks for {asked} years; you fit {wanted}")
            return max(0.0, 100.0 - 50.0 * (required - ceiling))
        if required_max is not None and required_max < low - 1:
            reasons.append(f"Asks for {asked} years; junior for your {wanted}")
            return 45.0
        if required < low - 2:
            reasons.append(f"Asks for {asked} years; below the {wanted} you fit")
            return 60.0
        reasons.append(f"{asked} years fits your {wanted}")
        return 100.0

    @staticmethod
    def _location_score(candidate: CandidateProfile, job: NormalizedJob, reasons: list[str]) -> tuple[float, bool]:
        prefs = candidate.preferences
        if prefs.remote_preference == RemotePreference.REMOTE_ONLY and job.workplace_type in (
            WorkplaceType.ONSITE,
            WorkplaceType.HYBRID,
        ):
            reasons.append(f"{job.workplace_type.value.title()} role but you want remote only")
            return 0.0, False

        places = [*prefs.preferred_locations, candidate.location or ""]
        if prefs.remote_preference in (RemotePreference.ANY, RemotePreference.REMOTE_ONLY):
            places.append("Remote")
        matcher = LocationMatcher.from_preferences(places)
        if not matcher.active:
            return NEUTRAL, True

        fit = matcher.fit(job)
        if fit == LocationFit.MATCH:
            reasons.append(f"In your preferred location ({job.location})")
            return 100.0, True
        if fit == LocationFit.REMOTE_OK:
            reasons.append("Remote and open to your location")
            return 100.0, True
        if fit == LocationFit.UNKNOWN:
            reasons.append("Posting does not state a location")
            return NEUTRAL, True
        if job.workplace_type == WorkplaceType.REMOTE:
            reasons.append(f"Remote but restricted to {job.location}")
            return 25.0, True
        reasons.append(f"Located in {job.location}")
        return (60.0 if prefs.willing_to_relocate else 20.0), True

    @staticmethod
    def _sponsorship_score(candidate: CandidateProfile, job: NormalizedJob, reasons: list[str]) -> tuple[float, bool]:
        if not candidate.preferences.visa_sponsorship_required:
            return 100.0, True
        status = job.visa_sponsorship.status
        if status == VisaSponsorshipStatus.YES:
            reasons.append("Explicitly offers visa sponsorship")
            return 100.0, True
        if status == VisaSponsorshipStatus.NO:
            reasons.append("Explicitly does not sponsor visas")
            return 0.0, False
        return 50.0, True
