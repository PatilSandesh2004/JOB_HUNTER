"""Convert raw postings from any source into NormalizedJob records."""

import re
import uuid

from rapidfuzz import fuzz

from ai_service.app.schemas.job import NormalizedJob, RemoteScope, WorkplaceType
from ai_service.app.schemas.search import RawJobPosting
from ai_service.app.services.jobs.ats import detect_ats, slug_to_company
from ai_service.app.services.jobs.requirements import Salary, experience_range, parse_salary, split_skills
from ai_service.app.services.visa.visa_service import VisaIntelligenceService

JOB_ID_NAMESPACE = uuid.UUID("6f1c1d1e-8a43-4c36-9d55-2b9a7d0f1a10")

_NOISE_PARTS = {
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "smartrecruiters",
    "linkedin",
    "indeed",
    "glassdoor",
    "jobs",
    "careers",
    "job application",
    "apply",
    "job board",
    "linkedin.com",
    "indeed.com",
    "naukri.com",
    "job details",
}
_GREENHOUSE_TITLE = re.compile(r"^job application for (?P<title>.+?) at (?P<company>.+)$", re.I)
# LinkedIn search-result titles: "Acme hiring Senior AI Engineer in Bengaluru, Karnataka, India | LinkedIn".
_LINKEDIN_TITLE = re.compile(
    r"^(?P<company>.+?) hiring (?P<title>.+?)(?: in (?P<location>[^|]+?))?\s*(?:[|\-–—]\s*LinkedIn)?\s*$", re.I
)
# LinkedIn job URLs carry the company: /jobs/view/<title-slug>-at-<company-slug>-<id>
_LINKEDIN_SLUG = re.compile(r"/jobs/view/(?P<title>[\w%-]+?)-at-(?P<company>[\w%-]+?)-\d{6,}/?$")
_ELLIPSIS = re.compile(r"\s*(\.\.\.|…)\s*$")
_TITLE_SEPARATORS = re.compile(r"\s+[-–—|@·]\s+|\s+at\s+", re.I)
_COMPANY_SUFFIX = re.compile(r"\s+(careers?|jobs|job board|hiring)\s*$", re.I)

_REMOTE_SCOPES: list[tuple[RemoteScope, re.Pattern[str]]] = [
    (RemoteScope.WORLDWIDE, re.compile(r"\b(worldwide|anywhere|global(ly)?|work from anywhere)\b", re.I)),
    (
        RemoteScope.INDIA_ONLY,
        re.compile(r"\b(india|bengaluru|bangalore|hyderabad|pune|chennai|mumbai|delhi|noida|gurugram)\b", re.I),
    ),
    (RemoteScope.US_ONLY, re.compile(r"\b(usa|u\.s\.a?\.?|united states|us[- ]based|us only|americas?)\b", re.I)),
    (RemoteScope.UK_ONLY, re.compile(r"\b(uk|united kingdom|england|london)\b", re.I)),
    (RemoteScope.EU_ONLY, re.compile(r"\b(eu|europe|european union|emea|germany|berlin)\b", re.I)),
    (RemoteScope.ASIA, re.compile(r"\b(apac|asia|singapore|japan)\b", re.I)),
    (RemoteScope.TIMEZONE_RESTRICTED, re.compile(r"\b(utc|gmt|cet|est|pst|ist)\b|\btime ?zones?\b", re.I)),
]
_EMPLOYMENT_RE = re.compile(r"\b(full[- ]time|part[- ]time|contract(?:or)?|internship|freelance|temporary)\b", re.I)


class JobNormalizationService:
    def __init__(self) -> None:
        self.visa = VisaIntelligenceService()

    def normalize(self, raw: RawJobPosting, location_hints: list[str] | None = None) -> NormalizedJob:
        ats = detect_ats(raw.url)
        title, company = self._title_and_company(raw, ats.company_slug)
        text = f"{title}\n{raw.snippet}\n{' '.join(raw.tags)}"
        workplace = WorkplaceType(raw.workplace) if raw.workplace else self._workplace(text, raw.remote)
        location = (
            raw.location
            or _title_location(raw.title, ats.name)
            or self._location_from_hints(text, location_hints or [])
        )
        required, preferred = split_skills(text)
        min_years, max_years = experience_range(text)
        salary = _salary(raw, text)

        return NormalizedJob(
            id=str(uuid.uuid5(JOB_ID_NAMESPACE, raw.url.split("?")[0].rstrip("/"))),
            title=title,
            company=company,
            description=raw.snippet,
            location=location or ("Remote" if workplace == WorkplaceType.REMOTE else "Unknown"),
            workplace_type=workplace,
            # Verified postings state their location; full descriptions mention "global"/"US clients" too loosely.
            remote_scope=self._remote_scope(
                location if raw.verified and location else f"{location or ''} {text}", workplace
            ),
            employment_type=_first_group(_EMPLOYMENT_RE, text),
            salary_min=salary.minimum if salary else None,
            salary_max=salary.maximum if salary else None,
            salary_currency=salary.currency if salary else None,
            salary_period=salary.period if salary else None,
            experience_required=min_years,
            experience_max=max_years,
            required_skills=required,
            preferred_skills=preferred,
            visa_sponsorship=self.visa.evaluate_sponsorship(text, raw.url),
            application_url=raw.url,
            ats=ats.name,
            source=raw.source,
            verified=raw.verified,
            posted_at=raw.posted_at,
        )

    @staticmethod
    def _title_and_company(raw: RawJobPosting, slug: str | None) -> tuple[str, str]:
        """Split page titles like 'Title - Company', 'Company - Title' (Lever) or 'Title @ Company'."""
        page_title = raw.title.strip()
        greenhouse = _GREENHOUSE_TITLE.match(page_title)
        if greenhouse:
            return greenhouse.group("title").strip(), raw.company or _clean_company(greenhouse.group("company"))
        if "linkedin." in raw.url:
            return _linkedin_title_and_company(raw)

        parts = [p.strip() for p in _TITLE_SEPARATORS.split(page_title)]
        parts = [p for p in parts if p and p.lower() not in _NOISE_PARTS]
        if not parts:
            return page_title, raw.company or "Unknown company"

        known_company = raw.company or (slug_to_company(slug) if slug else None)
        if known_company:
            key = _squash(known_company)
            remaining = [p for p in parts if fuzz.partial_ratio(_squash(p), key) < 80] or parts
            return max(remaining, key=len), known_company
        if len(parts) >= 2 and len(parts[1]) <= 60:
            return parts[0], _clean_company(parts[1])
        return parts[0], "Unknown company"

    @staticmethod
    def _workplace(text: str, remote_flag: bool | None) -> WorkplaceType:
        if re.search(r"\bhybrid\b", text, re.I):
            return WorkplaceType.HYBRID
        if remote_flag or re.search(r"\b(remote|work from home|wfh|distributed team)\b", text, re.I):
            return WorkplaceType.REMOTE
        if re.search(r"\b(on-?site|in[- ]office|in person)\b", text, re.I):
            return WorkplaceType.ONSITE
        return WorkplaceType.UNKNOWN

    @staticmethod
    def _remote_scope(text: str, workplace: WorkplaceType) -> RemoteScope:
        if workplace != WorkplaceType.REMOTE:
            return RemoteScope.NOT_REMOTE if workplace != WorkplaceType.UNKNOWN else RemoteScope.UNKNOWN
        for scope, pattern in _REMOTE_SCOPES:
            if pattern.search(text):
                return scope
        return RemoteScope.UNKNOWN

    @staticmethod
    def _location_from_hints(text: str, hints: list[str]) -> str | None:
        for hint in hints:
            if hint.lower() != "remote" and re.search(rf"\b{re.escape(hint)}\b", text, re.I):
                return hint
        return None


def refresh_requirements(job: NormalizedJob) -> NormalizedJob:
    """Re-read skills, experience and (missing) salary from a stored description, e.g. after the parsers
    improved, so jobs saved by an older version are scored like new ones."""
    if not job.description:
        return job
    text = f"{job.title}\n{job.description}"
    required, preferred = split_skills(text)
    min_years, max_years = experience_range(text)
    update: dict = {
        "required_skills": required,
        "preferred_skills": preferred,
        "experience_required": min_years,
        "experience_max": max_years,
    }
    if job.salary_min is None and job.salary_max is None and (salary := parse_salary(text)):
        update |= {
            "salary_min": salary.minimum,
            "salary_max": salary.maximum,
            "salary_currency": salary.currency,
            "salary_period": salary.period,
        }
    return job.model_copy(update=update)


def _salary(raw: RawJobPosting, text: str) -> Salary | None:
    """Pay stated by the source's API, else the first salary range written in the posting."""
    if raw.salary_min is not None or raw.salary_max is not None:
        low = raw.salary_min if raw.salary_min is not None else raw.salary_max
        high = raw.salary_max if raw.salary_max is not None else raw.salary_min
        return Salary(low, high, (raw.salary_currency or "USD").upper(), raw.salary_period or "year")
    return parse_salary(text)


def _linkedin_title_and_company(raw: RawJobPosting) -> tuple[str, str]:
    """LinkedIn titles come as 'Company hiring Title in City | LinkedIn' or 'Title - Company - LinkedIn'.

    The URL's '<title>-at-<company>-<id>' slug is the most reliable company source; the page title gives
    the nicer spelling ('C5i' rather than 'C5i'.title()) when both agree.
    """
    page_title = raw.title.strip()
    slug = _LINKEDIN_SLUG.search(raw.url.split("?")[0])
    slug_company = slug_to_company(slug.group("company")) if slug else None
    hiring = _LINKEDIN_TITLE.match(page_title)
    if hiring:
        title, company = hiring.group("title").strip(), hiring.group("company").strip()
    else:
        parts = [p.strip() for p in _TITLE_SEPARATORS.split(page_title)]
        parts = [p for p in parts if p and p.lower() not in _NOISE_PARTS] or [page_title]
        at = next((i for i, p in enumerate(parts) if slug_company and _squash(p) == _squash(slug_company)), None)
        if at:  # everything before the company is the title, e.g. "Junior AI Engineer - Backend Python - Acme"
            title, company = " - ".join(parts[:at]), parts[at]
        else:
            title, company = parts[0], parts[1] if len(parts) > 1 and len(parts[1]) <= 60 else "Unknown company"
    if raw.company:
        return title, raw.company
    if slug_company and _squash(company) != _squash(slug_company):
        company = slug_company
    return title, company


def _title_location(page_title: str, ats_name: str) -> str | None:
    """Location stated in an aggregator page title ('... hiring X in Bengaluru, India | LinkedIn')."""
    if ats_name != "aggregator":
        return None
    match = _LINKEDIN_TITLE.match(page_title.strip())
    if not match or not match.group("location"):
        return None
    return _ELLIPSIS.sub("", match.group("location")).strip(" ,") or None


def _clean_company(name: str) -> str:
    """'Future - Greenhouse' -> 'Future'; 'Ecolab Careers' -> 'Ecolab'."""
    parts = [p.strip() for p in _TITLE_SEPARATORS.split(name) if p.strip().lower() not in _NOISE_PARTS]
    cleaned = _COMPANY_SUFFIX.sub("", parts[0] if parts else name).strip()
    return cleaned or name.strip()


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).replace("-", " ").title() if match else None
