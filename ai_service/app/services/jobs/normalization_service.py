"""Convert raw postings from any source into NormalizedJob records."""

import re
import uuid

from rapidfuzz import fuzz

from ai_service.app.schemas.job import NormalizedJob, RemoteScope, WorkplaceType
from ai_service.app.schemas.search import RawJobPosting
from ai_service.app.services.jobs.ats import detect_ats, slug_to_company
from ai_service.app.services.skills.catalog import extract_skills
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
}
_GREENHOUSE_TITLE = re.compile(r"^job application for (?P<title>.+?) at (?P<company>.+)$", re.I)
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
_EXPERIENCE_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|to|–)?\s*(?:\d{1,2}\s*)?\+?\s*years?", re.I)
_EMPLOYMENT_RE = re.compile(r"\b(full[- ]time|part[- ]time|contract(?:or)?|internship|freelance|temporary)\b", re.I)


class JobNormalizationService:
    def __init__(self) -> None:
        self.visa = VisaIntelligenceService()

    def normalize(self, raw: RawJobPosting, location_hints: list[str] | None = None) -> NormalizedJob:
        ats = detect_ats(raw.url)
        title, company = self._title_and_company(raw, ats.company_slug)
        text = f"{title}\n{raw.snippet}\n{' '.join(raw.tags)}"
        workplace = WorkplaceType(raw.workplace) if raw.workplace else self._workplace(text, raw.remote)
        location = raw.location or self._location_from_hints(text, location_hints or [])

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
            experience_required=self._experience(text),
            required_skills=extract_skills(text),
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

    @staticmethod
    def _experience(text: str) -> float | None:
        values = [int(m.group(1)) for m in _EXPERIENCE_RE.finditer(text) if 0 < int(m.group(1)) <= 25]
        return float(min(values)) if values else None


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
