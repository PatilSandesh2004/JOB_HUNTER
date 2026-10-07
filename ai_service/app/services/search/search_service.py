"""Multi-source job discovery: SearXNG (ATS-targeted), Remotive and Arbeitnow."""

import asyncio
import html
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from ai_service.app.core.config import Settings, settings
from ai_service.app.integrations.search.searxng_client import SearXNGClient
from ai_service.app.integrations.search.serper_client import SerperClient
from ai_service.app.schemas.search import RawJobPosting
from ai_service.app.services.jobs.ats import ATS_SEARCH_SITES, detect_ats

if TYPE_CHECKING:
    from ai_service.app.services.search.board_source import BoardSearchSource

logger = logging.getLogger("jobpilot.search")

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# "Remote AI Engineer Jobs in the US", "1,234 Python jobs", "Jobs at Acme" are listing pages, not postings.
LISTING_TITLE_RE = re.compile(
    r"\bjobs\s+(in|near|for|at)\b|\b\d[\d,]*\+?\s+[\w\s-]*\bjobs\b|\bjob (openings|search)\b|^jobs at\b|\bjobs\s*[(|-]",
    re.I,
)


def strip_html(text: str | None, limit: int = 4000) -> str:
    # Unescape before stripping: some APIs (Greenhouse) return HTML-escaped HTML ("&lt;p&gt;").
    unescaped = html.unescape(text or "")
    cleaned = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", unescaped))).strip()
    return cleaned[:limit]


class SearchService:
    MAX_ATS_TARGETED_QUERIES = 2  # company boards are the primary source; keep web-search load low

    def __init__(
        self,
        searxng_client: SearXNGClient | SerperClient | None = None,
        config: Settings = settings,
        board_source: "BoardSearchSource | None" = None,
    ) -> None:
        self.config = config
        
        if searxng_client:
            self.searxng = searxng_client
        elif config.web_search_provider.lower() == "serper":
            self.searxng = SerperClient(config.serper_api_key, config.searxng_timeout_seconds)
        else:
            self.searxng = SearXNGClient(config.searxng_url, config.searxng_timeout_seconds)
            
        self.boards = board_source
        self._searxng_limit = asyncio.Semaphore(config.searxng_max_concurrency)

    async def search_many(
        self, queries: list[str], titles: list[str], locations: list[str] | None = None
    ) -> tuple[list[RawJobPosting], list[str]]:
        """Run every query against every enabled source concurrently. Returns (postings, errors)."""
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=self.config.external_api_timeout_seconds, verify=False) as client:
            tasks = [self._searxng_query(q, client) for q in self._expand_ats_queries(queries)]
            if self.config.search_enable_remotive:
                tasks += [self._remotive(role, client) for role in titles[:3]]
            if self.config.search_enable_arbeitnow:
                tasks.append(self._arbeitnow(titles, client))
            if self.boards is not None:
                tasks.append(self.boards.search(titles, locations or []))
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        postings: list[RawJobPosting] = []
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                errors.append(str(outcome))
                logger.warning("Search source failed: %s", outcome)
            else:
                postings.extend(outcome)
        if self.boards is not None:
            # Remember company boards found via web search so future searches query them directly.
            self.boards.remember_from_urls([p.url for p in postings if p.source == "searxng"])
        return postings, list(dict.fromkeys(errors))

    def _expand_ats_queries(self, queries: list[str]) -> list[str]:
        expanded = [f"{q} jobs" for q in queries]
        if self.config.search_ats_targeting:
            # Site-scoped variants only for the leading queries, to stay under engine rate limits.
            leading = queries[: self.MAX_ATS_TARGETED_QUERIES]
            expanded += [f"{q} site:{site}" for q in leading for site in ATS_SEARCH_SITES]
        # Job sites: group them to avoid generating dozens of web requests which deplete quotas.
        job_sites = self.config.search_job_sites
        if job_sites:
            chunk_size = 5
            for i in range(0, len(job_sites), chunk_size):
                chunk = job_sites[i:i + chunk_size]
                site_group = " OR ".join(f"site:{site}" for site in chunk)
                for q in queries[:1]:
                    expanded.append(f"{q} ({site_group})")
        return list(dict.fromkeys(expanded))

    async def _searxng_query(self, query: str, client: httpx.AsyncClient) -> list[RawJobPosting]:
        async with self._searxng_limit:
            try:
                results = await self.searxng.search(query, client=client)
            except Exception as exc:
                # No query in the message so identical engine failures collapse into one error line.
                raise RuntimeError(f"SearXNG: {exc}") from exc
        postings = []
        for item in results:
            url = item.get("url") or ""
            title = strip_html(item.get("title"), 300)
            if not url.startswith("http") or not detect_ats(url).is_posting or LISTING_TITLE_RE.search(title):
                continue  # drop articles, board indexes and search/listing pages
            postings.append(
                RawJobPosting(
                    title=title or "Untitled",
                    url=url,
                    snippet=strip_html(item.get("content")),
                    source="searxng",
                    engine=item.get("engine") or "serper",
                    posted_at=_parse_datetime(item.get("publishedDate")),
                )
            )
        return postings

    async def _remotive(self, search_term: str, client: httpx.AsyncClient) -> list[RawJobPosting]:
        try:
            response = await client.get(REMOTIVE_URL, params={"search": search_term, "limit": 25})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Remotive API failed: {exc}") from exc
        return [
            RawJobPosting(
                title=job.get("title", ""),
                url=job.get("url", ""),
                snippet=strip_html(job.get("description")),
                company=job.get("company_name"),
                location=job.get("candidate_required_location") or "Remote",
                remote=True,
                tags=job.get("tags") or [],
                source="remotive",
                posted_at=_parse_datetime(job.get("publication_date")),
            )
            for job in response.json().get("jobs", [])
            if job.get("url")
        ]

    async def _arbeitnow(self, role_keywords: list[str], client: httpx.AsyncClient) -> list[RawJobPosting]:
        """Arbeitnow has no server-side search, so filter its latest page by role keywords."""
        try:
            response = await client.get(ARBEITNOW_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Arbeitnow API failed: {exc}") from exc
        keyword_sets = [set(_tokens(role)) for role in role_keywords]
        postings = []
        for job in response.json().get("data", []):
            title_tokens = set(_tokens(job.get("title", "")))
            if not any(ks and ks <= title_tokens for ks in keyword_sets):
                continue
            postings.append(
                RawJobPosting(
                    title=job.get("title", ""),
                    url=job.get("url", ""),
                    snippet=strip_html(job.get("description")),
                    company=job.get("company_name"),
                    location=job.get("location"),
                    remote=job.get("remote"),
                    tags=job.get("tags") or [],
                    source="arbeitnow",
                    posted_at=_parse_datetime(job.get("created_at")),
                )
            )
        return postings


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", text.lower())


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value, tz=UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, OSError):
        return None
