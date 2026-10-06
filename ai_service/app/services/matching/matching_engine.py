"""Explainable candidate-to-job scoring."""

import re

from rapidfuzz import fuzz

from ai_service.app.schemas.candidate import CandidateProfile, RemotePreference
from ai_service.app.schemas.job import NormalizedJob, VisaSponsorshipStatus, WorkplaceType
from ai_service.app.schemas.match import MatchResult
from ai_service.app.services.jobs.location_service import LocationFit, LocationMatcher
from ai_service.app.services.skills.catalog import normalize_skill_list

WEIGHTS = {"title": 0.25, "skills": 0.35, "experience": 0.15, "location": 0.15, "sponsorship": 0.10}
NEUTRAL = 60.0  # score used when the posting does not give enough information to judge
SKILL_PRIOR = 2  # pseudo-count of "unknown" skills blended into small skill lists


# Words that say nothing about *which* role it is.
_GENERIC_TITLE_WORDS = {
    "engineer",
    "engineering",
    "developer",
    "senior",
    "sr",
    "junior",
    "jr",
    "staff",
    "principal",
    "lead",
    "head",
    "of",
    "the",
    "and",
    "i",
    "ii",
    "iii",
    "iv",
    "remote",
    "hybrid",
    "contract",
    "intern",
    "associate",
    "specialist",
    "mid",
    "level",
    "entry",
    "f",
    "m",
    "d",
    "w",
    "x",
}
# Phrase -> canonical token, applied before tokenising.
_TITLE_PHRASES = [
    (r"machine learning|artificial intelligence|generative ai|gen ?ai|applied ai|llms?|nlp|deep learning", "ai"),
    (r"\bml\b", "ai"),
    (r"back[- ]end", "backend"),
    (r"front[- ]end", "frontend"),
    (r"full[- ]stack", "fullstack"),
    (r"dev[- ]?ops|site reliability|\bsre\b|platform", "devops"),
    (r"data scien\w*", "datascience"),
    (r"software|\bswe\b|\bsde\b", "software"),
]


def _role_tokens(title: str) -> set[str]:
    text = title.lower()
    for pattern, token in _TITLE_PHRASES:
        text = re.sub(pattern, f" {token} ", text)
    return {t for t in re.findall(r"[a-z0-9+#.]+", text) if t not in _GENERIC_TITLE_WORDS}


def role_similarity(target: str, title: str) -> float:
    """0-100: how well a job title matches a target role, ignoring seniority/generic words."""
    wanted, have = _role_tokens(target), _role_tokens(title)
    fuzzy = max(0.0, min(100.0, (fuzz.token_sort_ratio(target.lower(), title.lower()) - 40) / 50 * 100))
    if not wanted:  # target like "Engineer": nothing specific, so its plain words must appear
        plain = set(re.findall(r"[a-z0-9+#.]+", target.lower()))
        return 100.0 if plain and plain <= set(re.findall(r"[a-z0-9+#.]+", title.lower())) else fuzzy
    coverage = len(wanted & have) / len(wanted)
    return 75 * coverage + 25 * fuzzy / 100


class MatchingEngineService:
    def evaluate_match(self, candidate: CandidateProfile, job: NormalizedJob) -> MatchResult:
        reasons: list[str] = []
        title_score = self._title_score(candidate, job, reasons)
        skill_score, matched, missing = self._skill_score(candidate, job, reasons)
        exp_score = self._experience_score(candidate, job, reasons)
        loc_score, loc_ok = self._location_score(candidate, job, reasons)
        sponsor_score, sponsor_ok = self._sponsorship_score(candidate, job, reasons)
        passed = loc_ok and sponsor_ok

        overall = (
            title_score * WEIGHTS["title"]
            + skill_score * WEIGHTS["skills"]
            + exp_score * WEIGHTS["experience"]
            + loc_score * WEIGHTS["location"]
            + sponsor_score * WEIGHTS["sponsorship"]
        )
        # A great fit on skills/location is worthless if the role itself is unrelated.
        relevance = min(1.0, 0.4 + title_score / 100)
        if relevance < 1.0:
            overall *= relevance
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
            matched_skills=matched,
            missing_skills=missing,
            passed_hard_filters=passed,
            reasons=reasons,
        )

    @staticmethod
    def _title_score(candidate: CandidateProfile, job: NormalizedJob, reasons: list[str]) -> float:
        targets = [*candidate.preferences.preferred_roles, candidate.current_role or ""]
        targets = [t for t in targets if t]
        if not targets:
            return NEUTRAL
        best_target, score = max(((t, role_similarity(t, job.title)) for t in targets), key=lambda pair: pair[1])
        if score >= 80:
            reasons.append(f"Title closely matches target role '{best_target}'")
        elif score < 30:
            reasons.append("Title differs from your target roles")
        return score

    @staticmethod
    def _skill_score(
        candidate: CandidateProfile, job: NormalizedJob, reasons: list[str]
    ) -> tuple[float, list[str], list[str]]:
        candidate_skills = {s.lower() for s in normalize_skill_list(candidate.skills)}
        required = job.required_skills
        if not required:
            reasons.append("Posting snippet lists no recognisable skills; skill fit not scored")
            return NEUTRAL, [], []
        matched = [s for s in required if s.lower() in candidate_skills]
        missing = [s for s in required if s.lower() not in candidate_skills]
        raw = 100.0 * len(matched) / len(required)
        # Snippets often list only one or two skills; shrink toward neutral so 1/1 is not "100% fit".
        confidence = len(required) / (len(required) + SKILL_PRIOR)
        score = confidence * raw + (1 - confidence) * NEUTRAL
        reasons.append(f"Matches {len(matched)}/{len(required)} listed skills")
        return score, matched, missing

    @staticmethod
    def _experience_score(candidate: CandidateProfile, job: NormalizedJob, reasons: list[str]) -> float:
        required = job.experience_required
        if required is None:
            return NEUTRAL + 15
        gap = required - candidate.years_of_experience
        if gap <= 0:
            reasons.append(f"Meets the {required:g}+ years requirement")
            return 100.0
        reasons.append(f"Asks for {required:g}+ years; you have {candidate.years_of_experience:g}")
        return max(0.0, 100.0 - 25.0 * gap)

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
