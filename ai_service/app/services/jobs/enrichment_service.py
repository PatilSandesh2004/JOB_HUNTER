"""Verify ATS postings through each ATS's public job API.

Search snippets rarely say where a job is. The ATS APIs return the real title, company, location,
workplace type and full description, and a 404 tells us the posting has closed.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from ai_service.app.schemas.search import RawJobPosting
from ai_service.app.services.jobs.ats import AtsInfo, detect_ats, slug_to_company
from ai_service.app.services.search.search_service import strip_html

logger = logging.getLogger("jobpilot.enrichment")

_WORKPLACE = {
    "remote": "REMOTE",
    "hybrid": "HYBRID",
    "onsite": "ONSITE",
    "on-site": "ONSITE",
    "on_site": "ONSITE",
    "in_office": "ONSITE",
    "office": "ONSITE",
}
DESCRIPTION_LIMIT = 8000


class PostingClosedError(Exception):
    pass


class JobEnrichmentService:
    def __init__(
        self, timeout: float = 8.0, concurrency: int = 8, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.timeout = timeout
        self.transport = transport  # injectable for tests
        self._limit = asyncio.Semaphore(concurrency)

    async def enrich(self, postings: list[RawJobPosting]) -> tuple[list[RawJobPosting], int]:
        """Return (postings with verified details, number of closed postings dropped)."""
        ashby_boards: dict[str, asyncio.Task] = {}
        async with httpx.AsyncClient(
            timeout=self.timeout, headers={"Accept": "application/json"}, transport=self.transport
        ) as client:
            outcomes = await asyncio.gather(*(self._enrich_one(p, client, ashby_boards) for p in postings))
        kept = [p for p in outcomes if p is not None]
        return kept, len(postings) - len(kept)

    async def check_open(self, urls: list[str]) -> list[bool | None]:
        """Per URL: True if the board confirms the posting is open, False if it is gone, None if unknown."""
        postings = [RawJobPosting(title="", url=url, source="recheck") for url in urls]
        ashby_boards: dict[str, asyncio.Task] = {}
        async with httpx.AsyncClient(
            timeout=self.timeout, headers={"Accept": "application/json"}, transport=self.transport
        ) as client:
            outcomes = await asyncio.gather(*(self._enrich_one(p, client, ashby_boards) for p in postings))
        return [False if o is None else (True if o.verified else None) for o in outcomes]

    async def _enrich_one(
        self, posting: RawJobPosting, client: httpx.AsyncClient, ashby_boards: dict[str, asyncio.Task]
    ) -> RawJobPosting | None:
        info = detect_ats(posting.url)
        fetcher = {
            "greenhouse": self._greenhouse,
            "lever": self._lever,
            "ashby": self._ashby,
            "workable": self._workable,
        }.get(info.name)
        if fetcher is None or not info.is_posting or posting.verified:
            return posting
        try:
            async with self._limit:
                details = await fetcher(info, client, ashby_boards)
        except PostingClosedError:
            return None
        except Exception as exc:  # network/format problems: keep the unverified posting
            logger.info("Could not verify %s: %s", posting.url, exc)
            return posting
        return posting.model_copy(
            update={**{k: v for k, v in details.items() if v not in (None, "")}, "verified": True}
        )

    # ---- per-ATS fetchers --------------------------------------------------
    @staticmethod
    async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
        response = await client.get(url)
        if response.status_code == 404:
            raise PostingClosedError(url)
        response.raise_for_status()
        return response.json()

    async def _greenhouse(self, info: AtsInfo, client: httpx.AsyncClient, _: dict) -> dict:
        data = await self._get_json(
            client, f"https://boards-api.greenhouse.io/v1/boards/{info.company_slug}/jobs/{info.job_id}"
        )
        location = (data.get("location") or {}).get("name")
        return {
            "title": data.get("title"),
            "company": data.get("company_name"),
            "location": location,
            "workplace": _workplace_from_text(location),
            "snippet": strip_html(data.get("content"), DESCRIPTION_LIMIT),
            "posted_at": _parse_dt(data.get("first_published") or data.get("updated_at")),
        }

    async def _lever(self, info: AtsInfo, client: httpx.AsyncClient, _: dict) -> dict:
        api_host = "api.eu.lever.co" if ".eu." in info.host else "api.lever.co"
        data = await self._get_json(client, f"https://{api_host}/v0/postings/{info.company_slug}/{info.job_id}")
        categories = data.get("categories") or {}
        locations = categories.get("allLocations") or [categories.get("location")]
        sections = " ".join(f"{s.get('text', '')}: {strip_html(s.get('content'))}" for s in data.get("lists") or [])
        return {
            "title": data.get("text"),
            "company": slug_to_company(info.company_slug or ""),
            "location": _join(*locations, data.get("country")),
            "workplace": _WORKPLACE.get(str(data.get("workplaceType", "")).lower()),
            "snippet": f"{data.get('descriptionPlain', '')} {sections} {data.get('additionalPlain', '')}"[
                :DESCRIPTION_LIMIT
            ],
            "posted_at": _parse_dt(data.get("createdAt")),
        }

    async def _ashby(self, info: AtsInfo, client: httpx.AsyncClient, boards: dict[str, asyncio.Task]) -> dict:
        # Ashby only exposes whole boards, so fetch each board once per search.
        slug = info.company_slug or ""
        if slug not in boards:
            boards[slug] = asyncio.ensure_future(
                self._get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
            )
        board = await boards[slug]
        job = next((j for j in board.get("jobs", []) if j.get("id") == info.job_id), None)
        if job is None:
            raise PostingClosedError(info.job_id)
        address = ((job.get("address") or {}).get("postalAddress")) or {}
        secondary = [s.get("location") for s in job.get("secondaryLocations") or []]
        workplace = _WORKPLACE.get(str(job.get("workplaceType") or "").lower()) or (
            "REMOTE" if job.get("isRemote") else None
        )
        return {
            "title": job.get("title"),
            "company": slug_to_company(slug),
            "location": _join(
                job.get("location"), address.get("addressRegion"), address.get("addressCountry"), *secondary
            ),
            "workplace": workplace,
            "snippet": (job.get("descriptionPlain") or "")[:DESCRIPTION_LIMIT],
            "posted_at": _parse_dt(job.get("publishedAt")),
        }

    async def _workable(self, info: AtsInfo, client: httpx.AsyncClient, _: dict) -> dict:
        data = await self._get_json(
            client, f"https://apply.workable.com/api/v2/accounts/{info.company_slug}/jobs/{info.job_id}"
        )
        places = data.get("locations") or [data.get("location") or {}]
        location = _join(*(_join(p.get("city"), p.get("region"), p.get("country")) for p in places if p))
        workplace = _WORKPLACE.get(str(data.get("workplace") or "").lower()) or (
            "REMOTE" if data.get("remote") else None
        )
        return {
            "title": data.get("title"),
            "company": slug_to_company(info.company_slug or ""),
            "location": location,
            "workplace": workplace,
            "snippet": strip_html(f"{data.get('description', '')} {data.get('requirements', '')}", DESCRIPTION_LIMIT),
            "posted_at": _parse_dt(data.get("published")),
        }


def _join(*parts: Any) -> str | None:
    values = [str(p).strip() for p in parts if p and str(p).strip()]
    return "; ".join(dict.fromkeys(values)) or None


def _workplace_from_text(text: str | None) -> str | None:
    lowered = (text or "").lower()
    if "hybrid" in lowered:
        return "HYBRID"
    if "remote" in lowered:
        return "REMOTE"
    return None


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, OSError):
        return None
