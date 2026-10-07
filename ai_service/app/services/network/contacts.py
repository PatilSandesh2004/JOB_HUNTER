"""Find people at a company to ask for a referral: your own LinkedIn connections, plus public profiles that
web search returns for the company's recruiters and team members (search results only; LinkedIn itself
is never scraped or logged into).
"""

import logging
import re
from typing import Any, Protocol
from urllib.parse import quote_plus

logger = logging.getLogger("jobpilot.network")

MAX_PEOPLE = 6
_PROFILE_PATH = re.compile(r"linkedin\.com/in/[\w%-]+", re.I)
_TITLE_SUFFIX = re.compile(r"\s*[|\-–—]\s*LinkedIn\s*$", re.I)


class WebSearch(Protocol):
    async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]: ...


def _profile(result: dict[str, Any]) -> dict[str, str] | None:
    """A LinkedIn member profile from a search result; company pages, job posts and schools are skipped."""
    url = result.get("url") or ""
    if not _PROFILE_PATH.search(url):
        return None
    title = _TITLE_SUFFIX.sub("", (result.get("title") or "").strip())
    if not title:
        return None
    return {"title": title, "url": url, "snippet": result.get("content") or ""}


def _people_search_url(company: str, keywords: str) -> str:
    return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(f'{company} {keywords}')}"


class CompanyContactsService:
    def __init__(self, search: WebSearch) -> None:
        self.search = search

    async def find(self, company: str, job_title: str | None = None) -> dict[str, Any]:
        """Recruiters and team members at `company`; team members are matched to the role when one is given."""
        team = job_title or "Engineer"
        queries = {
            "recruiters": f'site:linkedin.com/in "{company}" ("Talent Acquisition" OR "Recruiter" OR "HR")',
            "employees": f'site:linkedin.com/in "{company}" "{team}"',
        }
        found: dict[str, list[dict[str, str]]] = {}
        errors: list[str] = []
        for key, query in queries.items():
            try:
                results = await self.search.search(query)
            except Exception as exc:  # web search is best effort; the LinkedIn links below always work
                logger.warning("Contact search failed for %s: %s", company, exc)
                errors.append(str(exc))
                results = []
            people = [p for p in (_profile(r) for r in results) if p]
            found[key] = list({p["url"]: p for p in people}.values())[:MAX_PEOPLE]
        return {
            "company": company,
            "linkedin_search_hr": _people_search_url(company, "Recruiter Talent Acquisition"),
            "linkedin_search_emp": _people_search_url(company, team),
            "recruiters": found["recruiters"],
            "employees": found["employees"],
            "errors": list(dict.fromkeys(errors)),
        }
