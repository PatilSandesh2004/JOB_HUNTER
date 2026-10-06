"""Search company job boards directly through the public Greenhouse / Lever / Ashby APIs.

Web search engines rate-limit quickly; these APIs return every open job of a company with an exact
location. Boards come from a verified seed list plus every board discovered via web search
(persisted in data/boards.json), so coverage grows with use.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from ai_service.app.schemas.search import RawJobPosting
from ai_service.app.services.jobs.ats import detect_ats, slug_to_company
from ai_service.app.services.jobs.location_service import LocationFit, LocationMatcher
from ai_service.app.services.matching.matching_engine import role_similarity
from ai_service.app.services.search.search_service import strip_html

logger = logging.getLogger("jobpilot.boards")

# Verified 2026-10: boards with open roles in India (most in Bengaluru).
SEED_BOARDS: dict[str, tuple[str, ...]] = {
    "greenhouse": (
        "airbnb",
        "anthropic",
        "coinbase",
        "databricks",
        "datadog",
        "druva",
        "elastic",
        "figma",
        "fivetran",
        "gitlab",
        "groww",
        "hackerrank",
        "mongodb",
        "newrelic",
        "observeai",
        "okta",
        "rubrik",
        "samsara",
        "sigmoid",
        "stripe",
        "toast",
        "turing",
        "twilio",
        "zscaler",
    ),
    "lever": ("cred", "fampay", "hevodata", "meesho", "mindtickle", "nium", "paytm", "pocketfm", "zeta"),
    "ashby": ("atlys", "composio", "elevenlabs", "harvey", "notion", "openai", "plane", "sarvam", "smallest", "writer"),
}
BOARD_ATS = tuple(SEED_BOARDS)
RELEVANCE_THRESHOLD = 50.0
MAX_PER_BOARD = 15
CACHE_TTL_SECONDS = 20 * 60


class BoardSearchSource:
    def __init__(
        self,
        registry_path: Path,
        timeout: float = 15.0,
        concurrency: int = 12,
        transport: httpx.AsyncBaseTransport | None = None,
        seeds: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.registry_path = registry_path
        self.timeout = timeout
        self.transport = transport  # injectable for tests
        self.seeds = SEED_BOARDS if seeds is None else seeds
        self._limit = asyncio.Semaphore(concurrency)
        self._cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}
        self._discovered = self._load_registry()

    # ---- board registry ----------------------------------------------------
    def boards(self) -> list[tuple[str, str]]:
        seeds = {(ats, slug) for ats, slugs in self.seeds.items() for slug in slugs}
        return sorted(seeds | self._discovered)

    def remember_from_urls(self, urls: list[str]) -> int:
        """Add boards seen in web-search results so future searches query them directly."""
        new = set()
        for url in urls:
            info = detect_ats(url)
            if info.name in BOARD_ATS and info.company_slug:
                new.add((info.name, info.company_slug.lower()))
        new -= self._discovered
        if new:
            self._discovered |= new
            self._save_registry()
        return len(new)

    def _load_registry(self) -> set[tuple[str, str]]:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            return {(ats, slug) for ats, slugs in data.items() if ats in BOARD_ATS for slug in slugs}
        except (OSError, ValueError):
            return set()

    def _save_registry(self) -> None:
        grouped: dict[str, list[str]] = {}
        for ats, slug in sorted(self._discovered):
            grouped.setdefault(ats, []).append(slug)
        try:
            self.registry_path.write_text(json.dumps(grouped, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not save board registry: %s", exc)

    # ---- search --------------------------------------------------------------
    async def search(self, titles: list[str], locations: list[str]) -> list[RawJobPosting]:
        matcher = LocationMatcher.from_preferences(locations)
        async with httpx.AsyncClient(
            timeout=self.timeout, headers={"Accept": "application/json"}, transport=self.transport
        ) as client:
            boards = await asyncio.gather(*(self._board(ats, slug, client) for ats, slug in self.boards()))

        postings: list[RawJobPosting] = []
        for jobs in boards:
            scored = []
            for job in jobs:
                relevance = max((role_similarity(t, job.title) for t in titles), default=0.0)
                if relevance < RELEVANCE_THRESHOLD:
                    continue
                if matcher.active and matcher.fit_values(job.location, job.title, job.workplace == "REMOTE") not in (
                    LocationFit.MATCH,
                    LocationFit.REMOTE_OK,
                ):
                    continue
                scored.append((relevance, job))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            postings += [job for _, job in scored[:MAX_PER_BOARD]]
        return postings

    async def _board(self, ats: str, slug: str, client: httpx.AsyncClient) -> list[RawJobPosting]:
        cached = self._cache.get((ats, slug))
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            raw_jobs = cached[1]
        else:
            try:
                async with self._limit:
                    raw_jobs = await self._fetch(ats, slug, client)
            except Exception as exc:
                logger.info("Board %s/%s unavailable: %s", ats, slug, exc)
                return []
            self._cache[(ats, slug)] = (time.monotonic(), raw_jobs)
        parse = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}[ats]
        return [p for p in (parse(slug, j) for j in raw_jobs) if p is not None]

    @staticmethod
    async def _fetch(ats: str, slug: str, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        url = {
            "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
            "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
        }[ats]
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else data.get("jobs", [])


def _greenhouse(slug: str, job: dict[str, Any]) -> RawJobPosting | None:
    # Listing has no description; the enrichment step fetches it for the jobs that survive filtering.
    url = job.get("absolute_url")
    if not url or not job.get("title"):
        return None
    location = (job.get("location") or {}).get("name")
    return RawJobPosting(
        title=job["title"],
        url=url,
        company=job.get("company_name") or slug_to_company(slug),
        location=location,
        workplace="REMOTE" if location and "remote" in location.lower() else None,
        source="company_board",
    )


def _lever(slug: str, job: dict[str, Any]) -> RawJobPosting | None:
    url = job.get("hostedUrl")
    if not url or not job.get("text"):
        return None
    categories = job.get("categories") or {}
    locations = categories.get("allLocations") or [categories.get("location")]
    workplace = {"remote": "REMOTE", "hybrid": "HYBRID", "onsite": "ONSITE"}.get(str(job.get("workplaceType")).lower())
    sections = " ".join(f"{s.get('text', '')}: {strip_html(s.get('content'))}" for s in job.get("lists") or [])
    return RawJobPosting(
        title=job["text"],
        url=url,
        snippet=f"{job.get('descriptionPlain', '')} {sections}"[:8000],
        company=slug_to_company(slug),
        location="; ".join(dict.fromkeys(str(x) for x in locations if x)) or None,
        workplace=workplace,
        source="company_board",
        verified=True,
    )


def _ashby(slug: str, job: dict[str, Any]) -> RawJobPosting | None:
    url = job.get("jobUrl")
    if not url or not job.get("title") or job.get("isListed") is False:
        return None
    address = ((job.get("address") or {}).get("postalAddress")) or {}
    secondary = [s.get("location") for s in job.get("secondaryLocations") or []]
    places = [job.get("location"), address.get("addressCountry"), *secondary]
    workplace = {"remote": "REMOTE", "hybrid": "HYBRID", "onsite": "ONSITE"}.get(str(job.get("workplaceType")).lower())
    return RawJobPosting(
        title=job["title"],
        url=url,
        snippet=(job.get("descriptionPlain") or "")[:8000],
        company=slug_to_company(slug),
        location="; ".join(dict.fromkeys(str(p) for p in places if p)) or None,
        workplace=workplace or ("REMOTE" if job.get("isRemote") else None),
        source="company_board",
        verified=True,
    )
