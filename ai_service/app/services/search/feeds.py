"""Public job feeds: Remotive, Arbeitnow, Remote OK, Himalayas, Jobicy and (with a free API key) Adzuna.

Each feed is fetched rarely and cached, then filtered locally: Remotive, for one, asks callers to fetch at most
a few times a day. Every job links back to the feed's own page and is labelled with the feed's name, as their
terms ask. Remote-only feeds are skipped when the search is for on-site jobs only.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from ai_service.app.core.config import Settings, settings
from ai_service.app.core.text import parse_datetime, strip_html
from ai_service.app.schemas.search import RawJobPosting
from ai_service.app.services.jobs.location_service import LocationMatcher
from ai_service.app.services.jobs.requirements import parse_salary
from ai_service.app.services.matching.roles import role_similarity

logger = logging.getLogger("jobpilot.feeds")

FEED_RELEVANCE = 40.0  # loose title filter; the search agent applies the real one with the description
DESCRIPTION_LIMIT = 8000
_PERIODS = {"annual": "year", "yearly": "year", "year": "year", "monthly": "month", "month": "month",
            "hourly": "hour", "hour": "hour"}  # fmt: skip
ADZUNA_COUNTRIES = {
    "india": ("in", "INR"), "united kingdom": ("gb", "GBP"), "united states": ("us", "USD"), "germany": ("de", "EUR"),
    "canada": ("ca", "CAD"), "australia": ("au", "AUD"), "singapore": ("sg", "SGD"), "netherlands": ("nl", "EUR"),
}  # fmt: skip


def relevant(title: str, titles: list[str]) -> bool:
    return max((role_similarity(t, title) for t in titles), default=0.0) >= FEED_RELEVANCE


class Feed:
    name = "feed"
    ttl_seconds = 3 * 3600
    remote_only = True

    def __init__(self, config: Settings = settings) -> None:
        self.config = config
        self._cache: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def enabled(self) -> bool:
        return True

    async def _get_json(self, client: httpx.AsyncClient, url: str, params: dict | None = None) -> Any:
        """GET with a per-URL cache, so repeated searches do not hit the feed again within `ttl_seconds`."""
        key = f"{url}?{sorted((params or {}).items())}"
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < self.ttl_seconds:
                return cached[1]
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise RuntimeError(f"{self.name} feed failed: {exc}") from exc
            self._cache[key] = (time.monotonic(), data)
            return data

    async def fetch(
        self, titles: list[str], locations: list[str], client: httpx.AsyncClient, max_days: int | None = None
    ) -> list[RawJobPosting]:
        raise NotImplementedError


def _salary_fields(text: str | None) -> dict[str, Any]:
    salary = parse_salary(text or "")
    if salary is None:
        return {}
    return {
        "salary_min": salary.minimum,
        "salary_max": salary.maximum,
        "salary_currency": salary.currency,
        "salary_period": salary.period,
    }


class RemotiveFeed(Feed):
    name = "Remotive"
    ttl_seconds = 6 * 3600  # Remotive asks for at most ~4 requests a day

    def enabled(self) -> bool:
        return self.config.search_enable_remotive

    async def fetch(self, titles, locations, client, max_days=None):
        data = await self._get_json(client, "https://remotive.com/api/remote-jobs")
        postings = []
        for job in data.get("jobs", []):
            if not job.get("url") or not relevant(job.get("title", ""), titles):
                continue
            postings.append(
                RawJobPosting(
                    title=job.get("title", ""),
                    url=job["url"],
                    snippet=strip_html(job.get("description"), DESCRIPTION_LIMIT),
                    company=job.get("company_name"),
                    location=job.get("candidate_required_location") or "Worldwide",
                    remote=True,
                    workplace="REMOTE",
                    tags=[*(job.get("tags") or []), *([job["job_type"]] if job.get("job_type") else [])],
                    source="remotive",
                    posted_at=parse_datetime(job.get("publication_date")),
                    **_salary_fields(job.get("salary")),
                )
            )
        return postings


class ArbeitnowFeed(Feed):
    name = "Arbeitnow"
    ttl_seconds = 3600
    remote_only = False  # mostly European office and remote jobs

    def enabled(self) -> bool:
        return self.config.search_enable_arbeitnow

    async def fetch(self, titles, locations, client, max_days=None):
        data = await self._get_json(client, "https://www.arbeitnow.com/api/job-board-api")
        postings = []
        for job in data.get("data", []):
            if not job.get("url") or not relevant(job.get("title", ""), titles):
                continue
            postings.append(
                RawJobPosting(
                    title=job.get("title", ""),
                    url=job["url"],
                    snippet=strip_html(job.get("description"), DESCRIPTION_LIMIT),
                    company=job.get("company_name"),
                    location=job.get("location"),
                    remote=job.get("remote"),
                    tags=job.get("tags") or [],
                    source="arbeitnow",
                    posted_at=parse_datetime(job.get("created_at")),
                )
            )
        return postings


class RemoteOKFeed(Feed):
    name = "Remote OK"
    ttl_seconds = 6 * 3600

    def enabled(self) -> bool:
        return self.config.search_enable_remoteok

    async def fetch(self, titles, locations, client, max_days=None):
        data = await self._get_json(client, "https://remoteok.com/api")
        postings = []
        for job in data if isinstance(data, list) else []:
            if not isinstance(job, dict) or not job.get("position") or not job.get("url"):
                continue  # the first element is the API's legal notice
            if not relevant(job["position"], titles):
                continue
            low, high = job.get("salary_min") or None, job.get("salary_max") or None
            salary = {"salary_min": low, "salary_max": high, "salary_currency": "USD"} if low or high else {}
            postings.append(
                RawJobPosting(
                    title=job["position"],
                    url=job["url"],
                    snippet=strip_html(job.get("description"), DESCRIPTION_LIMIT),
                    company=job.get("company"),
                    location=job.get("location") or "Worldwide",
                    remote=True,
                    workplace="REMOTE",
                    tags=job.get("tags") or [],
                    source="remoteok",
                    posted_at=parse_datetime(job.get("date") or job.get("epoch")),
                    **salary,
                )
            )
        return postings


class HimalayasFeed(Feed):
    name = "Himalayas"

    def enabled(self) -> bool:
        return self.config.search_enable_himalayas

    async def fetch(self, titles, locations, client, max_days=None):
        results = await asyncio.gather(
            *(
                self._get_json(client, "https://himalayas.app/jobs/api/search", {"q": title, "limit": 20})
                for title in titles[:3]
            ),
            return_exceptions=True,
        )
        postings: dict[str, RawJobPosting] = {}
        for data in results:
            if isinstance(data, BaseException):
                logger.info("Himalayas search failed: %s", data)
                continue
            for job in data.get("jobs", []):
                url = job.get("applicationLink") or job.get("guid")
                if not url or url in postings or not relevant(job.get("title", ""), titles):
                    continue
                places = [p for p in job.get("locationRestrictions") or [] if p]
                salary = {}
                if job.get("minSalary") or job.get("maxSalary"):
                    salary = {
                        "salary_min": job.get("minSalary"),
                        "salary_max": job.get("maxSalary"),
                        "salary_currency": job.get("currency") or "USD",
                        "salary_period": _PERIODS.get(str(job.get("salaryPeriod") or "").lower(), "year"),
                    }
                postings[url] = RawJobPosting(
                    title=job.get("title", ""),
                    url=url,
                    snippet=strip_html(job.get("description") or job.get("excerpt"), DESCRIPTION_LIMIT),
                    company=job.get("companyName"),
                    location="; ".join(places) if places else "Worldwide",
                    remote=True,
                    workplace="REMOTE",
                    tags=[
                        *(job.get("seniority") or []),
                        *([job["employmentType"]] if job.get("employmentType") else []),
                    ],
                    source="himalayas",
                    posted_at=parse_datetime(job.get("pubDate")),
                    **salary,
                )
        return list(postings.values())


class JobicyFeed(Feed):
    name = "Jobicy"

    def enabled(self) -> bool:
        return self.config.search_enable_jobicy

    async def fetch(self, titles, locations, client, max_days=None):
        results = await asyncio.gather(
            *(
                self._get_json(client, "https://jobicy.com/api/v2/remote-jobs", {"count": 50, "tag": title})
                for title in titles[:2]
            ),
            return_exceptions=True,
        )
        postings: dict[str, RawJobPosting] = {}
        for data in results:
            if isinstance(data, BaseException):
                logger.info("Jobicy search failed: %s", data)
                continue
            for job in data.get("jobs", []):
                url = job.get("url")
                if not url or url in postings or not relevant(job.get("jobTitle", ""), titles):
                    continue
                salary = {}
                if job.get("annualSalaryMin") or job.get("annualSalaryMax"):
                    salary = {
                        "salary_min": job.get("annualSalaryMin"),
                        "salary_max": job.get("annualSalaryMax"),
                        "salary_currency": job.get("salaryCurrency") or "USD",
                        "salary_period": "year",
                    }
                postings[url] = RawJobPosting(
                    title=job.get("jobTitle", ""),
                    url=url,
                    snippet=strip_html(job.get("jobDescription") or job.get("jobExcerpt"), DESCRIPTION_LIMIT),
                    company=job.get("companyName"),
                    location=job.get("jobGeo") or "Worldwide",
                    remote=True,
                    workplace="REMOTE",
                    tags=[job["jobLevel"]] if job.get("jobLevel") else [],
                    source="jobicy",
                    posted_at=parse_datetime(job.get("pubDate")),
                    **salary,
                )
        return list(postings.values())


class AdzunaFeed(Feed):
    """Adzuna's job search API (free key from developer.adzuna.com). Covers India and many other countries,
    with salaries. Off unless ADZUNA_APP_ID and ADZUNA_APP_KEY are set."""

    name = "Adzuna"
    remote_only = False

    def enabled(self) -> bool:
        return bool(self.config.adzuna_app_id and self.config.adzuna_app_key)

    @staticmethod
    def country_for(locations: list[str]) -> tuple[str, str]:
        countries = LocationMatcher.from_preferences(locations).countries
        for country in countries:
            if country in ADZUNA_COUNTRIES:
                return ADZUNA_COUNTRIES[country]
        return ADZUNA_COUNTRIES["india"]

    async def fetch(self, titles, locations, client, max_days=None):
        country, currency = self.country_for(locations)
        places = [p for p in locations if p.lower() not in ("remote", "anywhere", "worldwide")][:2] or [""]
        params_base: dict[str, Any] = {
            "app_id": self.config.adzuna_app_id,
            "app_key": self.config.adzuna_app_key,
            "results_per_page": 50,
            "content-type": "application/json",
        }
        if max_days:
            params_base["max_days_old"] = max_days
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
        requests = [
            params_base | {"what": title} | ({"where": place} if place else {})
            for title in titles[:2]
            for place in places
        ]
        results = await asyncio.gather(*(self._get_json(client, url, p) for p in requests), return_exceptions=True)
        postings: dict[str, RawJobPosting] = {}
        for data in results:
            if isinstance(data, BaseException):
                logger.info("Adzuna search failed: %s", data)
                continue
            for job in data.get("results", []):
                link, title = job.get("redirect_url"), strip_html(job.get("title"), 300)
                if not link or link in postings or not relevant(title, titles):
                    continue
                salary = {}
                if str(job.get("salary_is_predicted", "0")) == "0" and (job.get("salary_min") or job.get("salary_max")):
                    salary = {
                        "salary_min": job.get("salary_min"),
                        "salary_max": job.get("salary_max"),
                        "salary_currency": currency,
                        "salary_period": "year",
                    }
                postings[link] = RawJobPosting(
                    title=title,
                    url=link,
                    snippet=strip_html(job.get("description"), DESCRIPTION_LIMIT),
                    company=(job.get("company") or {}).get("display_name"),
                    location=(job.get("location") or {}).get("display_name"),
                    tags=[t for t in (job.get("contract_time"), job.get("contract_type")) if t],
                    source="adzuna",
                    posted_at=parse_datetime(job.get("created")),
                    **salary,
                )
        return list(postings.values())


def default_feeds(config: Settings = settings) -> list[Feed]:
    return [
        RemotiveFeed(config),
        ArbeitnowFeed(config),
        RemoteOKFeed(config),
        HimalayasFeed(config),
        JobicyFeed(config),
        AdzunaFeed(config),
    ]
