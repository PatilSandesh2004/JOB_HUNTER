"""LangGraph search workflow.

plan_queries -> search_sources -> verify_postings -> normalize_and_filter -> rank

Roles and locations default to the candidate's profile, and the LLM writes extra queries from the
resume (titles, seniority, strongest skills), so "Search from my resume" needs no typing.
"""

import logging
import re
from collections import Counter

from langgraph.graph import END, START, StateGraph

from ai_service.app.agents.search_agent.state import SearchAgentState
from ai_service.app.core.errors import JobPilotError, LLMUnavailableError
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.schemas.candidate import CandidateProfile, RemotePreference
from ai_service.app.schemas.job import VisaSponsorshipStatus, WorkplaceType
from ai_service.app.schemas.match import JobWithMatch
from ai_service.app.schemas.search import SearchQueryRequest, SearchResponse
from ai_service.app.services.jobs.deduplication_service import JobDeduplicationService
from ai_service.app.services.jobs.enrichment_service import JobEnrichmentService
from ai_service.app.services.jobs.location_service import CITIES, LocationFit, LocationMatcher
from ai_service.app.services.jobs.normalization_service import JobNormalizationService
from ai_service.app.services.matching.matching_engine import MatchingEngineService, role_similarity
from ai_service.app.services.search.search_service import SearchService

logger = logging.getLogger("jobpilot.search_agent")

MAX_QUERIES = 7
MAX_LLM_QUERIES = 3
RELEVANCE_THRESHOLD = 40.0  # role_similarity below this to every target title = unrelated job

_EXPANSION_SYSTEM = "You are a recruiter who writes precise job-board search queries. Respond with a JSON object only."
_EXPANSION_USER = """Write {n} web search queries to find open job postings for this candidate.

Candidate:
- Target roles: {roles}
- Current role: {current_role}
- Years of experience: {years}
- Recent titles: {titles}
- Strongest skills: {skills}
- Locations: {locations}

Return JSON {{"titles": [...], "queries": [...]}}:
- "titles": up to 6 real job titles this candidate should apply for, based on their roles, experience
  and skills (e.g. "Machine Learning Engineer", "Backend Engineer (Python)"). No seniority words.
- "queries": {n} web search queries, each "<job title> <location>", max 7 words, matching the
  candidate's seniority (e.g. "Senior Python Backend Engineer Bengaluru"), always including one of the
  candidate's locations, no site: operators, no quotes, no boolean words."""


class SearchInputError(JobPilotError):
    pass


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
    queries = []
    for role in roles:
        for location in locations or [""]:
            if location.lower() == "remote":
                queries.append(f"{role} remote")
            else:
                suffix = " remote" if remote_only else ""
                queries.append(f"{role} {location}{suffix}".strip())
    # Search engines index both spellings of renamed Indian cities (Bengaluru/Bangalore).
    for location in locations:
        aliases = next((a for a, _ in CITIES.values() if location.lower() in a), ())
        for alias in aliases[:2]:
            if alias != location.lower() and roles:
                queries.append(f"{roles[0]} {alias.title()}")
    return list(dict.fromkeys(queries))


class SearchAgent:
    def __init__(
        self,
        search_service: SearchService,
        llm: LLMClient,
        enricher: JobEnrichmentService | None = None,
        normalizer: JobNormalizationService | None = None,
        deduper: JobDeduplicationService | None = None,
        matcher: MatchingEngineService | None = None,
    ) -> None:
        self.search_service = search_service
        self.llm = llm
        self.enricher = enricher
        self.normalizer = normalizer or JobNormalizationService()
        self.deduper = deduper or JobDeduplicationService()
        self.matcher = matcher or MatchingEngineService()
        self.graph = self._build()

    async def run(self, request: SearchQueryRequest, candidate: CandidateProfile | None) -> SearchResponse:
        roles, locations = resolve_targets(request, candidate)
        state: SearchAgentState = await self.graph.ainvoke(
            {
                "request": request,
                "candidate": candidate,
                "roles": roles,
                "locations": locations,
                "errors": [],
                "filtered_out": {},
            }
        )
        return SearchResponse(
            roles=roles,
            locations=locations,
            titles=state.get("titles", roles),
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
        base = build_base_queries(roles, locations, request.remote_only)
        llm_titles: list[str] = []
        llm_queries: list[str] = []
        errors: list[str] = []
        if request.use_llm_expansion and self.llm.available:
            try:
                llm_titles, llm_queries = await self._llm_plan(roles, locations, state.get("candidate"))
            except LLMUnavailableError as exc:
                errors.append(f"Query expansion skipped: {exc}")
        # Interleave so both typed roles and resume-derived titles survive the cap.
        merged: list[str] = []
        for i in range(max(len(base), len(llm_queries))):
            merged += [q for q in (base[i : i + 1] + llm_queries[i : i + 1])]
        queries = list(dict.fromkeys(q for q in merged if q))
        titles = list(dict.fromkeys([*roles, *llm_titles]))
        return {"queries": queries[:MAX_QUERIES], "titles": titles, "errors": errors}

    async def _llm_plan(
        self, roles: list[str], locations: list[str], candidate: CandidateProfile | None
    ) -> tuple[list[str], list[str]]:
        """Related job titles and search queries derived from the resume."""
        data = await self.llm.complete_json(
            _EXPANSION_SYSTEM,
            _EXPANSION_USER.format(
                n=MAX_LLM_QUERIES,
                roles=", ".join(roles),
                current_role=(candidate.current_role if candidate else None) or "not stated",
                years=f"{candidate.years_of_experience:g}"
                if candidate and candidate.years_of_experience
                else "not stated",
                titles=", ".join(w.title for w in (candidate.work_experience if candidate else [])[:3]) or "not stated",
                skills=", ".join((candidate.skills if candidate else [])[:12]) or "not stated",
                locations=", ".join(locations) or "any",
            ),
            temperature=0.3,
            max_tokens=1500,
        )
        clean = lambda values: [re.sub(r"\s+", " ", v).strip() for v in values or [] if isinstance(v, str)]  # noqa: E731
        titles = [t for t in clean(data.get("titles")) if 2 <= len(t) <= 60][:6]
        queries = [q for q in clean(data.get("queries")) if q and "site:" not in q.lower()][:MAX_LLM_QUERIES]
        return titles, queries

    async def search_sources(self, state: SearchAgentState) -> dict:
        postings, errors = await self.search_service.search_many(
            state["queries"], state["titles"], state["locations"]
        )
        return {"raw_postings": postings, "errors": errors}

    async def verify_postings(self, state: SearchAgentState) -> dict:
        if self.enricher is None:
            return {"verified_postings": state["raw_postings"]}
        verified, closed = await self.enricher.enrich(state["raw_postings"])
        return {"verified_postings": verified, "filtered_out": {"closed": closed}}

    async def normalize_and_filter(self, state: SearchAgentState) -> dict:
        request, locations = state["request"], state["locations"]
        jobs = [self.normalizer.normalize(p, locations) for p in state["verified_postings"]]
        jobs = self.deduper.deduplicate(jobs)
        removed: Counter[str] = Counter(state.get("filtered_out", {}))

        # Broad sources (Remotive, web search) return loosely related jobs: keep those that fit a target title.
        titles = state.get("titles") or state["roles"]
        kept = [j for j in jobs if max(role_similarity(t, j.title) for t in titles) >= RELEVANCE_THRESHOLD]
        removed["unrelated role"] += len(jobs) - len(kept)
        jobs = kept

        if request.remote_only:
            kept = [j for j in jobs if j.workplace_type in (WorkplaceType.REMOTE, WorkplaceType.UNKNOWN)]
            removed["not remote"] += len(jobs) - len(kept)
            jobs = kept
        if request.sponsorship_required:
            kept = [j for j in jobs if j.visa_sponsorship.status != VisaSponsorshipStatus.NO]
            removed["no sponsorship"] += len(jobs) - len(kept)
            jobs = kept

        matcher = LocationMatcher.from_preferences(locations)
        if request.strict_location and matcher.active:
            kept = []
            for job in jobs:
                fit = matcher.fit(job)
                if fit in (LocationFit.MATCH, LocationFit.REMOTE_OK):
                    kept.append(job)
                else:
                    removed["other location" if fit == LocationFit.MISMATCH else "location unknown"] += 1
            jobs = kept
        return {"results": [JobWithMatch(job=j) for j in jobs], "filtered_out": dict(removed)}

    async def rank(self, state: SearchAgentState) -> dict:
        candidate = state.get("candidate")
        results = state["results"]
        if candidate is not None:
            results = [JobWithMatch(job=r.job, match=self.matcher.evaluate_match(candidate, r.job)) for r in results]
            results.sort(key=lambda r: (r.match.passed_hard_filters, r.match.overall_match), reverse=True)
        return {"results": results[: state["request"].max_results]}
