"""LangGraph search workflow.

plan_queries -> search_sources -> verify_postings -> normalize_and_filter -> rank

Roles and locations default to the candidate's profile. Queries come from four places, interleaved so each
survives the cap: the roles themselves, the other names those jobs are posted under ("AI Engineer" ->
"Machine Learning Engineer"), the resume (strongest skills for the role, seniority), and the LLM, which
reads the resume and work history and suggests titles and queries.
"""

import hashlib
import json
import logging
import re
import time
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from langgraph.graph import END, START, StateGraph

from ai_service.app.agents.search_agent.state import SearchAgentState
from ai_service.app.core.errors import JobPilotError, LLMUnavailableError
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.schemas.candidate import CandidateProfile, RemotePreference
from ai_service.app.schemas.job import NormalizedJob, VisaSponsorshipStatus, WorkplaceType
from ai_service.app.schemas.match import JobWithMatch
from ai_service.app.schemas.search import SearchProgress, SearchQueryRequest, SearchResponse
from ai_service.app.services.jobs.deduplication_service import JobDeduplicationService
from ai_service.app.services.jobs.enrichment_service import JobEnrichmentService
from ai_service.app.services.jobs.location_service import CITIES, LocationFit, LocationMatcher
from ai_service.app.services.jobs.normalization_service import JobNormalizationService
from ai_service.app.services.matching.feedback import FeedbackModel
from ai_service.app.services.matching.matching_engine import (
    MatchingEngineService,
    candidate_skill_profile,
    default_band,
    experience_band,
    title_seniority_conflict,
)
from ai_service.app.services.matching.reviewer import JobReviewer
from ai_service.app.services.matching.roles import parse_title, related_titles, role_similarity
from ai_service.app.services.matching.semantic import SemanticMatcher
from ai_service.app.services.search.search_service import SearchService
from ai_service.app.services.skills.catalog import SPECIALTY_DOMAINS, skill_domain

logger = logging.getLogger("jobpilot.search_agent")

MAX_QUERIES = 10
MAX_LLM_QUERIES = 3
RELEVANCE_THRESHOLD = 55.0  # role_similarity below this to every searched title = unrelated job
PLAN_CACHE_SECONDS = 6 * 3600  # the same profile and search reuse the LLM's plan instead of a new call
POSTED_WITHIN = {
    "24h": (timedelta(hours=24), "24 hours"),
    "7d": (timedelta(days=7), "a week"),
    "30d": (timedelta(days=30), "a month"),
}

_EXPANSION_SYSTEM = (
    "You are an expert technical recruiter who plans precise job searches. Use only the facts given. "
    "Respond with a JSON object only."
)
_EXPANSION_USER = """Plan a job search for this candidate.

Candidate:
- Target roles: {roles}
- Current role: {current_role}
- Total experience: {years} years (wants roles asking for {band} years)
- Recent experience:
{experience}
- Strongest skills: {skills}
- Locations: {locations}

Return JSON {{"titles": [...], "queries": [...], "skills": [...]}}:
- "titles": up to 6 job titles employers really use for the jobs this candidate should apply to, close to the
  target roles and to what they have actually done (e.g. "Machine Learning Engineer", "Backend Engineer (Python)").
  No seniority words, nothing unrelated.
- "queries": {n} web search queries of at most 7 words: "<job title> <location>", optionally with one key skill,
  at the candidate's seniority, each with one of the locations. No site: operators, quotes or boolean words.
- "skills": the 3 skills a recruiter would search for to find this candidate, most important first."""


class SearchInputError(JobPilotError):
    pass


STAGE_LABELS = {
    "plan_queries": "Planning searches",
    "search_sources": "Searching job boards",
    "verify_postings": "Verifying postings with the job boards",
    "normalize_and_filter": "De-duplicating and filtering",
    "rank": "Ranking against your profile",
}


def _describe(stage: str, update: dict) -> str:
    if stage == "plan_queries":
        return f"{len(update.get('queries', []))} queries for {len(update.get('titles', []))} job titles"
    if stage == "search_sources":
        return f"{len(update.get('raw_postings', []))} postings found"
    if stage == "verify_postings":
        closed = (update.get("filtered_out") or {}).get("closed", 0)
        return f"{len(update.get('verified_postings', []))} verified, {closed} closed"
    if stage == "normalize_and_filter":
        return f"{len(update.get('results', []))} jobs kept"
    if stage == "rank":
        return f"{len(update.get('results', []))} ranked"
    return ""


def resolve_targets(request: SearchQueryRequest, candidate: CandidateProfile | None) -> tuple[list[str], list[str]]:
    """Roles and locations to search: what the user typed, else their profile."""
    roles, locations = list(request.roles), list(request.locations)
    if candidate is not None:
        prefs = candidate.preferences
        if not roles:
            roles = prefs.preferred_roles or [r for r in [candidate.current_role] if r]
            if not roles and candidate.work_experience:
                roles = [candidate.work_experience[0].title]
        if not locations:
            locations = list(prefs.preferred_locations)
            if not locations and candidate.location:
                locations = [candidate.location.split(",")[0].strip()]
            wants_remote = prefs.remote_preference == RemotePreference.REMOTE_ONLY
            if wants_remote and "remote" not in {loc.lower() for loc in locations}:
                locations.append("Remote")
    if not roles:
        raise SearchInputError("Enter a role, or upload your resume / set target roles in your profile")
    return roles[:4], locations[:4]


def build_base_queries(roles: list[str], locations: list[str], remote_only: bool = False) -> list[str]:
    """One query per role and place; renamed Indian cities are searched under both names."""
    queries = []
    for role in roles:
        for location in locations or [""]:
            if location.lower() == "remote":
                queries.append(f"{role} remote")
            else:
                queries.append(f"{role} {location}{' remote' if remote_only else ''}".strip())
    # Search engines index both spellings of renamed Indian cities (Bengaluru/Bangalore).
    for location in locations:
        aliases = next((a for a, _ in CITIES.values() if location.lower() in a), ())
        for alias in aliases[:2]:
            if alias != location.lower() and roles:
                queries.append(f"{roles[0]} {alias.title()}")
    return list(dict.fromkeys(queries))


def effective_experience(request, candidate: CandidateProfile | None) -> str:
    """The experience range to search by: the user's choice, else the range around the resume's years."""
    chosen = getattr(request, "experience", "ANY") or "ANY"
    band = default_band(candidate.years_of_experience if candidate else None)
    if chosen == "ANY" and band:
        return f"{band[0]:g}-{band[1]:g}"
    return chosen


def _primary_place(locations: list[str]) -> str:
    place = next((p for p in locations if p.lower() not in ("remote", "anywhere", "worldwide")), "")
    return place or ("remote" if locations else "")


def query_skills(role: str, candidate: CandidateProfile, suggested: list[str] | None = None) -> list[str]:
    """Skills worth adding to a search for `role`: the LLM's picks, then the candidate's skills that belong to
    the role's kind of work (LLMs/RAG for an AI role, React for a frontend role), then other catalogue skills."""
    known, _ = candidate_skill_profile(candidate.skills)
    role_words = set(re.findall(r"[a-z0-9+#.]+", role.lower()))
    domains = {d for s in parse_title(role).specialties for d in SPECIALTY_DOMAINS.get(s, ())}
    ordered = [s for s in candidate.skills if s in known] + sorted(known - set(candidate.skills))
    on_topic = [s for s in ordered if skill_domain(s) in domains]
    other = [s for s in ordered if s not in on_topic and skill_domain(s) not in ("general", "language", None)]
    picks = [*(suggested or []), *on_topic, *other]
    return [s for s in dict.fromkeys(picks) if s.lower() not in role_words and len(s) <= 20][:4]


_SENIORITY_WORDS = re.compile(r"\b(senior|sr|junior|jr|lead|principal|staff|intern|fresher)\b", re.I)


def build_resume_queries(
    roles: list[str],
    locations: list[str],
    candidate: CandidateProfile | None,
    experience: str = "ANY",
    suggested_skills: list[str] | None = None,
) -> list[str]:
    """Queries that blend the searched role with the resume: strongest relevant skills and seniority."""
    if candidate is None or not roles:
        return []
    role, place = roles[0], _primary_place(locations)
    skills = query_skills(role, candidate, suggested_skills)
    queries = [f"{role} {' '.join(pair)} {place}".strip() for pair in (skills[0:2], skills[2:4]) if pair]
    band = experience_band(experience)
    years = candidate.years_of_experience or (band[0] if band else 0)
    if not _SENIORITY_WORDS.search(role):
        if years >= 6:
            queries.append(f"Senior {role} {place}".strip())
        elif 0 < years < 1:
            queries.append(f"{role} fresher {place}".strip())
        elif 0 < years <= 2.5:
            queries.append(f"Junior {role} {place}".strip())
    return queries


def _foreign_without_sponsorship(job: NormalizedJob, home_countries: set[str]) -> bool:
    if job.visa_sponsorship.status != VisaSponsorshipStatus.NO or not job.location:
        return False
    countries = LocationMatcher.from_preferences([job.location]).countries
    return bool(countries) and not countries & home_countries


@dataclass
class _Filters:
    """Everything the filters need, worked out once per search."""

    request: SearchQueryRequest
    titles: list[str]
    band: tuple[float, float | None] | None
    years: float | None
    blocked: set[str]
    home_countries: set[str]
    location: LocationMatcher
    cutoff: datetime | None
    cutoff_label: str

    def drop_reason(self, job: NormalizedJob) -> str | None:
        """Why a job is left out, or None to keep it."""
        skills = [*job.required_skills, *job.preferred_skills]
        if max(role_similarity(t, job.title, skills) for t in self.titles) < RELEVANCE_THRESHOLD:
            return "unrelated role"
        if self.band is not None or self.years is not None:
            low, high = self.band if self.band is not None else (0.0, None)
            ceiling = low if high is None else high
            required, required_max = job.experience_required, job.experience_max
            if title_seniority_conflict(job.title, self.band, self.years):
                return "seniority mismatch"
            if required is not None and required > ceiling + 0.5:
                return "needs more experience"
            if low >= 2 and required_max is not None and required_max < low - 1:
                return "too junior"
            if low >= 2 and required is not None and required_max is None and 0 < required < low - 2:
                return "too junior"
        if job.company.strip().lower() in self.blocked:
            return "company you hid"
        if self.request.remote_only and job.workplace_type not in (WorkplaceType.REMOTE, WorkplaceType.UNKNOWN):
            return "not remote"
        if self.request.sponsorship_required and job.visa_sponsorship.status == VisaSponsorshipStatus.NO:
            return "no sponsorship"
        if self.home_countries and _foreign_without_sponsorship(job, self.home_countries):
            return "abroad, no visa sponsorship"
        if self.cutoff is not None:
            posted = job.posted_at
            if posted is None:
                return "no posting date"
            if (posted if posted.tzinfo else posted.replace(tzinfo=UTC)) < self.cutoff:
                return f"posted more than {self.cutoff_label} ago"
        if self.request.strict_location and self.location.active:
            fit = self.location.fit(job)
            if fit not in (LocationFit.MATCH, LocationFit.REMOTE_OK):
                return "other location" if fit == LocationFit.MISMATCH else "location unknown"
        return None


class SearchAgent:
    def __init__(
        self,
        search_service: SearchService,
        llm: LLMClient,
        enricher: JobEnrichmentService | None = None,
        normalizer: JobNormalizationService | None = None,
        deduper: JobDeduplicationService | None = None,
        matcher: MatchingEngineService | None = None,
        semantic: SemanticMatcher | None = None,
        reviewer: JobReviewer | None = None,
    ) -> None:
        self.search_service = search_service
        self.llm = llm
        self.enricher = enricher
        self.normalizer = normalizer or JobNormalizationService()
        self.deduper = deduper or JobDeduplicationService()
        self.matcher = matcher or MatchingEngineService()
        self.semantic = semantic
        self.reviewer = reviewer
        self._plan_cache: dict[str, tuple[float, tuple[list[str], list[str], list[str]]]] = {}
        self.graph = self._build()

    async def run(
        self,
        request: SearchQueryRequest,
        candidate: CandidateProfile | None,
        feedback: FeedbackModel | None = None,
    ) -> SearchResponse:
        state: SearchAgentState = await self.graph.ainvoke(self.initial_state(request, candidate, feedback))
        return self.response(state)

    def initial_state(
        self,
        request: SearchQueryRequest,
        candidate: CandidateProfile | None,
        feedback: FeedbackModel | None = None,
    ) -> SearchAgentState:
        """Resolve roles/locations up front so bad input fails before any streaming starts."""
        roles, locations = resolve_targets(request, candidate)
        return {
            "request": request,
            "candidate": candidate,
            "roles": roles,
            "locations": locations,
            "errors": [],
            "filtered_out": {},
            "feedback": feedback,
        }

    async def stream(self, state: SearchAgentState) -> AsyncIterator[SearchProgress | SearchResponse]:
        """Yield a progress update after each stage, then the final response."""
        final: SearchAgentState = state
        async for mode, chunk in self.graph.astream(state, stream_mode=["updates", "values"]):
            if mode == "values":
                final = chunk
                continue
            for node, update in chunk.items():
                yield SearchProgress(stage=node, label=STAGE_LABELS.get(node, node), detail=_describe(node, update))
        yield self.response(final)

    @staticmethod
    def response(state: SearchAgentState) -> SearchResponse:
        return SearchResponse(
            roles=state["roles"],
            locations=state["locations"],
            titles=state.get("titles", state["roles"]),
            queries=state["queries"],
            total_raw=len(state["raw_postings"]),
            total_results=len(state["results"]),
            filtered_out={k: v for k, v in state["filtered_out"].items() if v},
            results=state["results"],
            errors=state["errors"],
        )

    def _build(self):
        builder = StateGraph(SearchAgentState)
        builder.add_node("plan_queries", self.plan_queries)
        builder.add_node("search_sources", self.search_sources)
        builder.add_node("verify_postings", self.verify_postings)
        builder.add_node("normalize_and_filter", self.normalize_and_filter)
        builder.add_node("rank", self.rank)
        builder.add_edge(START, "plan_queries")
        builder.add_edge("plan_queries", "search_sources")
        builder.add_edge("search_sources", "verify_postings")
        builder.add_edge("verify_postings", "normalize_and_filter")
        builder.add_edge("normalize_and_filter", "rank")
        builder.add_edge("rank", END)
        return builder.compile()

    # ---- nodes -----------------------------------------------------------
    async def plan_queries(self, state: SearchAgentState) -> dict:
        request, roles, locations = state["request"], state["roles"], state["locations"]
        candidate = state.get("candidate")
        band = effective_experience(request, candidate)
        base = build_base_queries(roles, locations, request.remote_only)
        typed = {r.lower() for r in roles}
        related = [
            t for t in dict.fromkeys(t for role in roles for t in related_titles(role)) if t.lower() not in typed
        ]
        place = _primary_place(locations)
        related_queries = [f"{title} {place}".strip() for title in related[:3]]

        llm_titles: list[str] = []
        llm_queries: list[str] = []
        llm_skills: list[str] = []
        errors: list[str] = []
        if request.use_llm_expansion and self.llm.available:
            try:
                llm_titles, llm_queries, llm_skills = await self._llm_plan(roles, locations, candidate, band)
            except LLMUnavailableError as exc:
                errors.append(f"Query expansion skipped: {exc}")
        resume_queries = build_resume_queries(roles, locations, candidate, band, llm_skills)

        # Interleave the sources so each survives the cap.
        merged: list[str] = []
        sources = [base, resume_queries, related_queries, llm_queries]
        for i in range(max(len(s) for s in sources)):
            for source in sources:
                merged += source[i : i + 1]
        queries = list(dict.fromkeys(q for q in merged if q))
        titles = list(dict.fromkeys([*roles, *related, *llm_titles]))
        return {"queries": queries[:MAX_QUERIES], "titles": titles, "errors": errors}

    async def _llm_plan(
        self, roles: list[str], locations: list[str], candidate: CandidateProfile | None, band: str
    ) -> tuple[list[str], list[str], list[str]]:
        """Related job titles, search queries and key skills, derived from the resume (cached per profile)."""
        experience = "\n".join(
            f"  - {w.title} at {w.company} ({w.start_date or '?'} to {w.end_date or 'present'}): "
            f"{(w.description or '').strip()[:220]}"
            for w in (candidate.work_experience if candidate else [])[:3]
        )
        years = candidate.years_of_experience if candidate else 0
        facts = {
            "roles": ", ".join(roles),
            "current_role": (candidate.current_role if candidate else None) or "not stated",
            "years": f"{years:g}" if years else "not stated",
            "band": band,
            "experience": experience or "  - not stated",
            "skills": ", ".join((candidate.skills if candidate else [])[:15]) or "not stated",
            "locations": ", ".join(locations) or "any",
        }
        key = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()
        cached = self._plan_cache.get(key)
        if cached and time.monotonic() - cached[0] < PLAN_CACHE_SECONDS:
            return cached[1]
        data = await self.llm.complete_json(
            _EXPANSION_SYSTEM,
            _EXPANSION_USER.format(n=MAX_LLM_QUERIES, **facts),
            temperature=0.2,
            max_tokens=1500,
        )

        def clean(values: object) -> list[str]:
            items = values if isinstance(values, list) else []
            return [re.sub(r"\s+", " ", v).strip() for v in items if isinstance(v, str) and v.strip()]

        titles = [t for t in clean(data.get("titles")) if 2 <= len(t) <= 60][:6]
        queries = [q for q in clean(data.get("queries")) if "site:" not in q.lower() and len(q) <= 80]
        skills = [s for s in clean(data.get("skills")) if len(s) <= 30][:3]
        plan = (titles, queries[:MAX_LLM_QUERIES], skills)
        self._plan_cache[key] = (time.monotonic(), plan)
        return plan

    async def search_sources(self, state: SearchAgentState) -> dict:
        request = state["request"]
        postings, errors = await self.search_service.search_many(
            state["queries"],
            state["titles"],
            state["locations"],
            posted_within=getattr(request, "posted_within", "any") or "any",
            remote_only=request.remote_only,
        )
        return {"raw_postings": postings, "errors": errors}

    async def verify_postings(self, state: SearchAgentState) -> dict:
        if self.enricher is None:
            return {"verified_postings": state["raw_postings"]}
        verified, closed = await self.enricher.enrich(state["raw_postings"])
        return {"verified_postings": verified, "filtered_out": {"closed": closed}}

    async def normalize_and_filter(self, state: SearchAgentState) -> dict:
        request, locations = state["request"], state["locations"]
        candidate = state.get("candidate")
        jobs = self.deduper.deduplicate([self.normalizer.normalize(p, locations) for p in state["verified_postings"]])
        posted_within = POSTED_WITHIN.get(getattr(request, "posted_within", "any") or "any")
        home = (
            LocationMatcher.from_preferences([candidate.location]).countries
            if candidate and candidate.location
            else set()
        )
        filters = _Filters(
            request=request,
            titles=state.get("titles") or state["roles"],
            band=experience_band(effective_experience(request, candidate)),
            years=candidate.years_of_experience if candidate and candidate.years_of_experience else None,
            blocked={c.strip().lower() for c in (candidate.preferences.blocked_companies if candidate else []) if c},
            home_countries=home,
            location=LocationMatcher.from_preferences(locations),
            cutoff=datetime.now(UTC) - posted_within[0] if posted_within else None,
            cutoff_label=posted_within[1] if posted_within else "",
        )
        removed: Counter[str] = Counter(state.get("filtered_out", {}))
        kept = []
        for job in jobs:
            reason = filters.drop_reason(job)
            if reason:
                removed[reason] += 1
            else:
                kept.append(job)
        return {"results": [JobWithMatch(job=j) for j in kept], "filtered_out": dict(removed)}

    async def rank(self, state: SearchAgentState) -> dict:
        candidate = state.get("candidate")
        results = state["results"]
        if candidate is not None:
            chosen = getattr(state["request"], "experience", "ANY")
            wanted = chosen if chosen and chosen != "ANY" else None  # else the candidate's own years decide
            similarity = await self.semantic.scores(candidate, [r.job for r in results]) if self.semantic else {}
            results = [
                JobWithMatch(
                    job=r.job,
                    match=self.matcher.evaluate_match(
                        candidate,
                        r.job,
                        wanted,
                        target_roles=state["roles"],
                        semantic=similarity.get(r.job.id),
                        feedback=state.get("feedback"),
                    ),
                )
                for r in results
            ]
            results.sort(key=lambda r: (r.match.passed_hard_filters, r.match.overall_match), reverse=True)
            if self.reviewer is not None:
                results = await self.reviewer.review(candidate, results)
        return {"results": results[: state["request"].max_results]}
