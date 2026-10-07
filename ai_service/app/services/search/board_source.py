"""Search company job boards directly through each ATS's public job-listing API.

Web search engines rate-limit quickly; these APIs return every open job of a company with an exact
location. Boards come from three places: a verified seed list, boards discovered in web-search results,
and companies you add to your watchlist. Discovered and watched boards persist in data/boards.json.

Supported: Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee and Personio. All are public,
documented endpoints meant for embedding a company's job list on other sites.
"""

import asyncio
import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ai_service.app.core.http import tls_verify
from ai_service.app.core.text import parse_datetime, strip_html
from ai_service.app.schemas.search import RawJobPosting
from ai_service.app.services.jobs.ats import detect_ats, slug_to_company
from ai_service.app.services.jobs.location_service import LocationFit, LocationMatcher
from ai_service.app.services.matching.roles import role_similarity
from ai_service.app.services.skills.catalog import extract_skills

logger = logging.getLogger("jobpilot.boards")

# Verified 2026-10 against each board's public API: companies with open roles in India or open to remote
# candidates (at least 5, or a large share of the board). 80 boards; a full refresh is ~60 MB, so it is cached.
SEED_BOARDS: dict[str, tuple[str, ...]] = {
    "greenhouse": (
        "affirm",
        "airbnb",
        "anthropic",
        "bitgo",
        "calendly",
        "canonical",
        "coinbase",
        "databricks",
        "datadog",
        "dropbox",
        "druva",
        "elastic",
        "fivetran",
        "gitlab",
        "glance",
        "grafanalabs",
        "groww",
        "gusto",
        "hackerrank",
        "highradius",
        "inmobi",
        "mercury",
        "mongodb",
        "monzo",
        "mozilla",
        "newrelic",
        "observeai",
        "okta",
        "okx",
        "pagerduty",
        "rubrik",
        "samsara",
        "sigmoid",
        "slice",
        "snorkelai",
        "stripe",
        "toast",
        "turing",
        "twilio",
        "vercel",
        "wikimedia",
        "zscaler",
    ),
    "lever": (
        "binance",
        "cred",
        "fampay",
        "hevodata",
        "meesho",
        "mindtickle",
        "nium",
        "paytm",
        "pocketfm",
        "toptal",
        "zeta",
    ),
    "ashby": (
        "andela",
        "anyscale",
        "atlan",
        "atlys",
        "bounce",
        "bureau",
        "cohere",
        "composio",
        "confluent",
        "cursor",
        "elevenlabs",
        "harvey",
        "langchain",
        "linear",
        "llamaindex",
        "notion",
        "openai",
        "perplexity",
        "plaid",
        "plane",
        "ramp",
        "replit",
        "sarvam",
        "smallest",
        "spotdraft",
        "writer",
        "zapier",
    ),
}
BOARD_ATS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee", "personio")
RELEVANCE_THRESHOLD = 55.0  # same bar as the search agent (services/matching/roles.py)
MAYBE_THRESHOLD = 40.0
MAX_PER_BOARD = 15
MAX_MAYBE_PER_BOARD = 5
CACHE_TTL_SECONDS = 3 * 3600  # boards change slowly; closed postings are re-checked separately
MAX_XML_BYTES = 5_000_000


class BoardError(ValueError):
    """A board URL that cannot be added (unsupported site, or the company has no public board)."""


@dataclass(frozen=True)
class Board:
    ats: str
    slug: str
    source: str  # "seed" | "discovered" | "watched"

    @property
    def company(self) -> str:
        return slug_to_company(self.slug)


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
        self._discovered, self._watched = self._load_registry()

    # ---- board registry ----------------------------------------------------
    def boards(self) -> list[tuple[str, str]]:
        return sorted({(b.ats, b.slug) for b in self.list_boards()})

    def list_boards(self) -> list[Board]:
        """Every board searched, labelled by where it came from (watched wins over discovered over seed)."""
        labelled: dict[tuple[str, str], str] = {}
        for ats, slugs in self.seeds.items():
            labelled.update({(ats, slug): "seed" for slug in slugs})
        labelled.update({key: "discovered" for key in self._discovered})
        labelled.update({key: "watched" for key in self._watched})
        return [Board(ats, slug, source) for (ats, slug), source in sorted(labelled.items())]

    def remember_from_urls(self, urls: list[str]) -> int:
        """Add boards seen in web-search results so future searches query them directly."""
        new = set()
        for url in urls:
            info = detect_ats(url)
            if info.name in BOARD_ATS and info.company_slug:
                new.add((info.name, info.company_slug.lower()))
        new -= self._discovered | self._watched
        if new:
            self._discovered |= new
            self._save_registry()
        return len(new)

    async def watch(self, url_or_board: str) -> tuple[Board, int]:
        """Add a company to the watchlist from any of its job URLs. Returns the board and its open jobs."""
        ats, slug = _parse_board(url_or_board)
        try:
            async with self._client() as client:
                jobs = await self._fetch(ats, slug, client)
        except Exception as exc:
            raise BoardError(f"Could not read the {ats} job board for '{slug}': {exc}") from exc
        self._cache[(ats, slug)] = (time.monotonic(), jobs)
        self._discovered.discard((ats, slug))
        self._watched.add((ats, slug))
        self._save_registry()
        return Board(ats, slug, "watched"), len(jobs)

    def forget(self, ats: str, slug: str) -> bool:
        """Remove a watched or discovered board. Built-in seed boards stay."""
        key = (ats, slug.lower())
        if key not in self._watched and key not in self._discovered:
            return False
        self._watched.discard(key)
        self._discovered.discard(key)
        self._save_registry()
        return True

    def _load_registry(self) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set(), set()
        # Older registries were a flat {ats: [slugs]} of discovered boards.
        sections = data if "discovered" in data or "watched" in data else {"discovered": data}

        def parse(section: dict) -> set[tuple[str, str]]:
            return {(ats, slug) for ats, slugs in (section or {}).items() if ats in BOARD_ATS for slug in slugs}

        return parse(sections.get("discovered")), parse(sections.get("watched"))

    def _save_registry(self) -> None:
        def group(keys: set[tuple[str, str]]) -> dict[str, list[str]]:
            grouped: dict[str, list[str]] = {}
            for ats, slug in sorted(keys):
                grouped.setdefault(ats, []).append(slug)
            return grouped

        payload = {"discovered": group(self._discovered), "watched": group(self._watched)}
        try:
            self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not save board registry: %s", exc)

    # ---- search --------------------------------------------------------------
    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout,
            headers={"Accept": "application/json, text/xml"},
            transport=self.transport,
            follow_redirects=True,
            verify=tls_verify(),
        )

    async def search(self, titles: list[str], locations: list[str]) -> list[RawJobPosting]:
        matcher = LocationMatcher.from_preferences(locations)
        async with self._client() as client:
            boards = await asyncio.gather(*(self._board(ats, slug, client) for ats, slug in self.boards()))

        postings: list[RawJobPosting] = []
        for jobs in boards:
            sure, maybe = [], []
            for job in jobs:
                if matcher.active and matcher.fit_values(job.location, job.title, job.workplace == "REMOTE") not in (
                    LocationFit.MATCH,
                    LocationFit.REMOTE_OK,
                ):
                    continue
                relevance = _relevance(job, titles)
                if relevance >= RELEVANCE_THRESHOLD:
                    sure.append((relevance, job))
                elif relevance >= MAYBE_THRESHOLD and not job.snippet:
                    # A generic title ("Software Engineer") with no description yet: the search agent decides
                    # once the description has been fetched.
                    maybe.append((relevance, job))
            sure.sort(key=lambda pair: pair[0], reverse=True)
            maybe.sort(key=lambda pair: pair[0], reverse=True)
            postings += [job for _, job in sure[:MAX_PER_BOARD]] + [job for _, job in maybe[:MAX_MAYBE_PER_BOARD]]
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
        parse = _PARSERS[ats]
        return [p for p in (parse(slug, j) for j in raw_jobs) if p is not None]

    @staticmethod
    async def _fetch(ats: str, slug: str, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        url = {
            "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
            "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
            "workable": f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
            "smartrecruiters": f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100",
            "recruitee": f"https://{slug}.recruitee.com/api/offers/",
            "personio": f"https://{slug}.jobs.personio.de/xml",
        }[ats]
        response = await client.get(url)
        response.raise_for_status()
        if ats == "personio":
            return _personio_positions(response.content)
        data = response.json()
        if isinstance(data, list):
            return data
        # SmartRecruiters reports an unknown company as an empty list, not a 404.
        jobs = data.get("jobs") or data.get("offers") or data.get("content") or []
        if ats == "workable":
            jobs = [j | {"company_name": data.get("name")} for j in jobs]
        return jobs


def _parse_board(value: str) -> tuple[str, str]:
    """`https://acme.recruitee.com/o/x`, `https://jobs.lever.co/acme`, or `lever:acme` -> (ats, slug)."""
    text = value.strip()
    if ":" in text and not text.lower().startswith("http"):
        ats, _, slug = text.partition(":")
        ats, slug = ats.strip().lower(), slug.strip()
    else:
        url = text if text.lower().startswith("http") else f"https://{text}"
        info = detect_ats(url)
        ats, slug = info.name, info.company_slug or ""
        if ats in BOARD_ATS and not slug:
            # A careers-page link (https://jobs.lever.co/acme) rather than one job: the company is the first segment.
            slug = next((part for part in urlparse(url).path.split("/") if part), "")
    if ats not in BOARD_ATS or not slug:
        raise BoardError(
            "Paste a job or careers-page link from Greenhouse, Lever, Ashby, Workable, SmartRecruiters, "
            "Recruitee or Personio (for example https://jobs.lever.co/acme)"
        )
    return ats, slug.lower()


def _relevance(job: RawJobPosting, titles: list[str]) -> float:
    """Title fit to the searched titles; a borderline title is re-judged with the skills in its description."""
    relevance = max((role_similarity(t, job.title) for t in titles), default=0.0)
    if MAYBE_THRESHOLD <= relevance < RELEVANCE_THRESHOLD and job.snippet:
        skills = extract_skills(job.snippet)
        relevance = max((role_similarity(t, job.title, skills) for t in titles), default=0.0)
    return relevance


_LEVER_INTERVALS = {"per-year-salary": "year", "per-month-salary": "month", "per-hour-wage": "hour"}
_ASHBY_INTERVALS = {"1 YEAR": "year", "1 MONTH": "month", "1 HOUR": "hour"}


def lever_salary(job: dict[str, Any]) -> dict[str, Any]:
    pay = job.get("salaryRange") or {}
    if not (pay.get("min") or pay.get("max")):
        return {}
    return {
        "salary_min": pay.get("min"),
        "salary_max": pay.get("max"),
        "salary_currency": pay.get("currency"),
        "salary_period": _LEVER_INTERVALS.get(str(pay.get("interval")), "year"),
    }


def ashby_salary(job: dict[str, Any]) -> dict[str, Any]:
    components = ((job.get("compensation") or {}).get("summaryComponents")) or []
    salary = next((c for c in components if str(c.get("compensationType")).lower() == "salary"), None)
    if not salary or not (salary.get("minValue") or salary.get("maxValue")):
        return {}
    return {
        "salary_min": salary.get("minValue"),
        "salary_max": salary.get("maxValue"),
        "salary_currency": salary.get("currencyCode"),
        "salary_period": _ASHBY_INTERVALS.get(str(salary.get("interval")).upper(), "year"),
    }


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
        posted_at=parse_datetime(job.get("first_published") or job.get("updated_at")),
        # absolute_url is often the company's own careers site; keep the board and id to fetch the description.
        board=f"greenhouse:{slug}",
        board_job_id=str(job["id"]) if job.get("id") else None,
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
        posted_at=parse_datetime(job.get("createdAt")),
        **lever_salary(job),
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
        posted_at=parse_datetime(job.get("publishedAt")),
        **ashby_salary(job),
    )


def _workable(slug: str, job: dict[str, Any]) -> RawJobPosting | None:
    if not job.get("shortcode") or not job.get("title"):
        return None
    place = ", ".join(p for p in (job.get("city"), job.get("state"), job.get("country")) if p)
    return RawJobPosting(
        title=job["title"],
        # The widget's short /j/<code> link has no account; this form is what the filler recognises.
        url=f"https://apply.workable.com/{slug}/j/{job['shortcode']}/",
        snippet=strip_html(job.get("description"), 8000),
        company=job.get("company_name") or slug_to_company(slug),
        location=place or None,
        workplace="REMOTE" if job.get("telecommuting") else None,
        source="company_board",
        verified=True,
        posted_at=parse_datetime(job.get("published_on") or job.get("created_at")),
    )


def _smartrecruiters(slug: str, job: dict[str, Any]) -> RawJobPosting | None:
    if not job.get("id") or not job.get("name"):
        return None
    location = job.get("location") or {}
    workplace = "REMOTE" if location.get("remote") else ("HYBRID" if location.get("hybrid") else None)
    return RawJobPosting(
        title=job["name"],
        url=f"https://jobs.smartrecruiters.com/{slug}/{job['id']}",
        company=(job.get("company") or {}).get("name") or slug_to_company(slug),
        location=location.get("fullLocation") or location.get("city"),
        workplace=workplace,
        source="company_board",
        verified=True,
        posted_at=parse_datetime(job.get("releasedDate")),
    )


def _recruitee(slug: str, job: dict[str, Any]) -> RawJobPosting | None:
    if not job.get("slug") or not job.get("title"):
        return None
    workplace = "REMOTE" if job.get("remote") else ("HYBRID" if job.get("hybrid") else None)
    return RawJobPosting(
        title=job["title"],
        # careers_url may be a custom domain; the recruitee.com address redirects there and is recognised.
        url=f"https://{slug}.recruitee.com/o/{job['slug']}",
        snippet=strip_html(f"{job.get('description') or ''} {job.get('requirements') or ''}", 8000),
        company=job.get("company_name") or slug_to_company(slug),
        location=job.get("location") or job.get("city"),
        workplace=workplace,
        source="company_board",
        verified=True,
        posted_at=parse_datetime(job.get("published_at") or job.get("created_at")),
    )


def _personio(slug: str, job: dict[str, Any]) -> RawJobPosting | None:
    if not job.get("id") or not job.get("name"):
        return None
    return RawJobPosting(
        title=job["name"],
        url=f"https://{slug}.jobs.personio.de/job/{job['id']}",
        snippet=strip_html(job.get("description"), 8000),
        company=job.get("subcompany") or slug_to_company(slug),
        location="; ".join(job.get("offices") or []) or None,
        source="company_board",
        verified=True,
        posted_at=parse_datetime(job.get("created_at")),
    )


def _personio_positions(content: bytes) -> list[dict[str, Any]]:
    """Personio publishes an XML feed; turn each <position> into a plain dict."""
    if len(content) > MAX_XML_BYTES:
        raise ValueError("Personio feed too large")
    root = ET.fromstring(content)
    positions = []
    for position in root.iter("position"):
        offices = [position.findtext("office") or ""] + [o.text or "" for o in position.iter("office")][1:]
        descriptions = " ".join(
            f"{d.findtext('name') or ''}: {d.findtext('value') or ''}" for d in position.iter("jobDescription")
        )
        positions.append(
            {
                "id": position.findtext("id"),
                "name": position.findtext("name"),
                "subcompany": position.findtext("subcompany"),
                "offices": [o.strip() for o in dict.fromkeys(offices) if o.strip()],
                "description": descriptions,
                "created_at": position.findtext("createdAt"),
            }
        )
    return positions


_PARSERS = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "workable": _workable,
    "smartrecruiters": _smartrecruiters,
    "recruitee": _recruitee,
    "personio": _personio,
}
