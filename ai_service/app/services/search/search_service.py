"""Multi-source job discovery: company job boards, web search (SearXNG or Serper) and public job feeds."""

import asyncio
import logging
import re
from typing import TYPE_CHECKING

import httpx

from ai_service.app.core.config import Settings, settings
from ai_service.app.core.http import tls_verify
from ai_service.app.core.text import parse_datetime, strip_html
from ai_service.app.integrations.search.searxng_client import SearXNGClient
from ai_service.app.integrations.search.serper_client import SerperClient
from ai_service.app.schemas.search import RawJobPosting
from ai_service.app.services.jobs.ats import ATS_SEARCH_SITES, detect_ats
from ai_service.app.services.search.feeds import Feed, default_feeds

if TYPE_CHECKING:
    from ai_service.app.services.search.board_source import BoardSearchSource

__all__ = ["LISTING_TITLE_RE", "SearchService", "strip_html"]

logger = logging.getLogger("jobpilot.search")

USER_AGENT = "JobPilot/0.3 (personal job search assistant)"
# "Remote AI Engineer Jobs in the US", "1,234 Python jobs", "Jobs at Acme" are listing pages, not postings.
LISTING_TITLE_RE = re.compile(
    r"\bjobs\s+(in|near|for|at)\b|\b\d[\d,]*\+?\s+[\w\s-]*\bjobs\b|\bjob (openings|search)\b|^jobs at\b|\bjobs\s*[(|-]",
    re.I,
)
TIME_RANGES = {"24h": ("day", 1), "7d": ("week", 7), "30d": ("month", 30)}  # posted_within -> (web, feed days)
_REMOTE_WORDS = {"remote", "anywhere", "worldwide", "wfh"}


class SearchService:
    MAX_ATS_TARGETED_QUERIES = 2  # company boards are the primary source; keep web-search load low

    def __init__(
        self,
        searxng_client: SearXNGClient | SerperClient | None = None,
        config: Settings = settings,
        board_source: "BoardSearchSource | None" = None,
        feeds: list[Feed] | None = None,
    ) -> None:
        self.config = config
        if searxng_client is not None:
            self.searxng = searxng_client
        elif config.web_search_provider.lower() == "serper":
            self.searxng = SerperClient(config.serper_api_key, config.searxng_timeout_seconds)
        else:
            self.searxng = SearXNGClient(config.searxng_url, config.searxng_timeout_seconds)
        self.boards = board_source
        self.feeds = default_feeds(config) if feeds is None else feeds
        self._searxng_limit = asyncio.Semaphore(config.searxng_max_concurrency)

    async def search_many(
        self,
        queries: list[str],
        titles: list[str],
        locations: list[str] | None = None,
        *,
        posted_within: str = "any",
        remote_only: bool = False,
    ) -> tuple[list[RawJobPosting], list[str]]:
        """Run every query against every enabled source concurrently. Returns (postings, errors)."""
        locations = locations or []
        time_range, max_days = TIME_RANGES.get(posted_within, (None, None))
        wants_remote = remote_only or not locations or any(p.lower() in _REMOTE_WORDS for p in locations)
        errors: list[str] = []
        async with httpx.AsyncClient(
            timeout=self.config.external_api_timeout_seconds,
            verify=tls_verify(),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            tasks = [self._web_query(q, client, time_range) for q in self._expand_ats_queries(queries)]
            for feed in self.feeds:
                if feed.enabled() and (wants_remote or not feed.remote_only):
                    tasks.append(feed.fetch(titles, locations, client, max_days))
            if self.boards is not None:
                tasks.append(self.boards.search(titles, locations))
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
        # Job sites (LinkedIn, Naukri, Indeed): read from search results only; the sites are never scraped.
        # One site: per query, because most engines ignore site: filters combined with OR.
        expanded += [f"{q} site:{site}" for q in queries[:1] for site in self.config.search_job_sites]
        return list(dict.fromkeys(expanded))

    async def _web_query(self, query: str, client: httpx.AsyncClient, time_range: str | None) -> list[RawJobPosting]:
        async with self._searxng_limit:
            try:
                results = await self.searxng.search(query, client=client, time_range=time_range)
            except Exception as exc:
                # No query in the message so identical engine failures collapse into one error line.
                raise RuntimeError(f"Web search: {exc}") from exc
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
                    posted_at=parse_datetime(item.get("publishedDate")),
                )
            )
        return postings
