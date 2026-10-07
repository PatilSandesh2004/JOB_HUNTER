"""AI review of the best matches: an LLM reads each posting against the profile and gives a verdict.

Catches what rules cannot: "PhD required", "5 years of Rust", "this is really a sales role". Only the top
results are reviewed, in batches, and verdicts are cached per job and profile so repeated searches and
re-scoring do not spend the LLM's rate limit again.
"""

import hashlib
import json
import logging

from ai_service.app.core.config import Settings, settings
from ai_service.app.core.errors import LLMUnavailableError
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.match import JobWithMatch, MatchResult

logger = logging.getLogger("jobpilot.reviewer")

BATCH_SIZE = 8
EXCERPT = 700
VERDICTS = ("strong", "possible", "weak", "no")

_SYSTEM = (
    "You are a meticulous technical recruiter. Judge each job's fit for the candidate strictly from the facts "
    "given; never assume skills or experience that are not stated. Respond with a JSON object only."
)
_USER = """Candidate: {role}, {years} years of experience. Wants: {targets} in {locations}.
Skills: {skills}
Recent work:
{work}

Jobs:
{jobs}

For every job return {{"id": "<number>", "verdict": "strong" | "possible" | "weak" | "no",
"reason": "<at most 20 words: the deciding fact>"}}.
strong = likely to get an interview; possible = worth applying; weak = a major gap; no = wrong kind of role,
wrong seniority, or a hard requirement the candidate clearly does not meet.
Return {{"reviews": [...]}}"""


def profile_fingerprint(candidate: CandidateProfile) -> str:
    facts = [
        candidate.current_role,
        candidate.years_of_experience,
        sorted(candidate.skills),
        [w.title for w in candidate.work_experience],
        sorted(candidate.preferences.preferred_roles),
        sorted(candidate.preferences.preferred_locations),
    ]
    return hashlib.sha256(json.dumps(facts, default=str).encode()).hexdigest()[:16]


def apply_verdict(match: MatchResult, verdict: str, reason: str, fingerprint: str) -> MatchResult:
    """Fold an AI verdict into the score: strong +5, weak -12, no caps the match at 40."""
    overall = match.overall_match
    if verdict == "strong":
        overall = min(100.0, overall + 5)
    elif verdict == "weak":
        overall = max(0.0, overall - 12)
    elif verdict == "no":
        overall = min(overall - 20, 40.0)
    label = {"strong": "Strong fit", "possible": "Possible fit", "weak": "Weak fit", "no": "Not a fit"}[verdict]
    return match.model_copy(
        update={
            "overall_match": round(max(0.0, overall), 1),
            "ai_verdict": verdict,
            "ai_reason": reason,
            "ai_profile": fingerprint,
            "reasons": [*match.reasons, f"AI review: {label}. {reason}".strip()],
        }
    )


def carry_over(previous: MatchResult | None, match: MatchResult, fingerprint: str) -> MatchResult:
    """Re-apply the AI verdict of an earlier score when the profile has not changed since."""
    if previous and previous.ai_verdict in VERDICTS and previous.ai_profile == fingerprint:
        return apply_verdict(match, previous.ai_verdict, previous.ai_reason or "", fingerprint)
    return match


class JobReviewer:
    def __init__(self, llm: LLMClient, config: Settings = settings) -> None:
        self.llm = llm
        self.top_n = config.llm_review_top_n
        self._cache: dict[tuple[str, str], tuple[str, str]] = {}

    @property
    def available(self) -> bool:
        return self.llm.available and self.top_n > 0

    def cached(self, job_id: str, fingerprint: str) -> tuple[str, str] | None:
        return self._cache.get((job_id, fingerprint))

    def remember(self, job_id: str, fingerprint: str, verdict: str, reason: str) -> None:
        self._cache[(job_id, fingerprint)] = (verdict, reason)

    async def review(self, candidate: CandidateProfile, items: list[JobWithMatch]) -> list[JobWithMatch]:
        """Review the top results (by current score); returns all items, re-sorted. Never raises."""
        if not self.available or not items:
            return items
        fingerprint = profile_fingerprint(candidate)
        top = [i for i in items if i.match and i.match.passed_hard_filters][: self.top_n]
        todo = [i for i in top if self.cached(i.job.id, fingerprint) is None]
        for start in range(0, len(todo), BATCH_SIZE):
            batch = todo[start : start + BATCH_SIZE]
            try:
                verdicts = await self._ask(candidate, batch)
            except LLMUnavailableError as exc:
                logger.warning("AI review skipped: %s", exc)
                break
            for item, (verdict, reason) in verdicts.items():
                self.remember(item, fingerprint, verdict, reason)
        reviewed = []
        for item in items:
            hit = self.cached(item.job.id, fingerprint) if item.match else None
            reviewed.append(
                JobWithMatch(job=item.job, match=apply_verdict(item.match, *hit, fingerprint)) if hit else item
            )
        reviewed.sort(
            key=lambda r: (bool(r.match and r.match.passed_hard_filters), r.match.overall_match if r.match else 0),
            reverse=True,
        )
        return reviewed

    async def _ask(self, candidate: CandidateProfile, batch: list[JobWithMatch]) -> dict[str, tuple[str, str]]:
        lines = []
        for number, item in enumerate(batch, 1):
            job = item.job
            years = (
                f"{job.experience_required:g}-{job.experience_max:g}"
                if job.experience_required is not None and job.experience_max is not None
                else (f"{job.experience_required:g}+" if job.experience_required is not None else "not stated")
            )
            lines.append(
                f"[{number}] {job.title} at {job.company} | {job.location} | asks {years} years | "
                f"skills: {', '.join(job.required_skills[:10]) or 'not listed'}\n"
                f"    {(job.description or 'No description.')[:EXCERPT]}"
            )
        prompt = _USER.format(
            role=candidate.current_role or "not stated",
            years=f"{candidate.years_of_experience:g}",
            targets=", ".join(candidate.preferences.preferred_roles or [candidate.current_role or "similar roles"]),
            locations=", ".join(candidate.preferences.preferred_locations) or "any location",
            skills=", ".join(candidate.skills[:30]) or "not stated",
            work="\n".join(f"- {w.title} at {w.company}" for w in candidate.work_experience[:3]) or "- not stated",
            jobs="\n".join(lines),
        )
        data = await self.llm.complete_json(_SYSTEM, prompt, temperature=0.0, max_tokens=1800)
        results: dict[str, tuple[str, str]] = {}
        for review in data.get("reviews") or []:
            if not isinstance(review, dict):
                continue
            try:
                item = batch[int(str(review.get("id")).strip("[] ")) - 1]
            except (ValueError, IndexError):
                continue
            verdict = str(review.get("verdict", "")).lower().strip()
            if verdict in VERDICTS:
                results[item.job.id] = (verdict, str(review.get("reason") or "").strip()[:200])
        return results
