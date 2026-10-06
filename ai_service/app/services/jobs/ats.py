"""Applicant-tracking-system (ATS) detection from posting URLs."""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# host regex, posting-path regex, apply-page suffix.
# The company slug is the path's group 1 (job id = group 2), or the host's named group "company" (job id =
# the path's group 1) for ATSs that give each company a subdomain.
_ATS_PATTERNS: dict[str, tuple[re.Pattern[str], re.Pattern[str], str]] = {
    "greenhouse": (
        re.compile(r"(^|\.)greenhouse\.io$"),
        re.compile(r"^/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)"),
        "",
    ),
    "lever": (re.compile(r"^jobs\.(eu\.)?lever\.co$"), re.compile(r"^/([\w.-]+)/([0-9a-f-]{36})"), "/apply"),
    "ashby": (
        re.compile(r"^jobs\.ashbyhq\.com$"),
        re.compile(r"^/([\w.%-]+)/([0-9a-f-]{36})"),
        "/application",
    ),
    "workable": (re.compile(r"^apply\.workable\.com$"), re.compile(r"^/([\w-]+)/j/([0-9A-F]+)", re.I), "/apply/"),
    "smartrecruiters": (re.compile(r"^jobs\.smartrecruiters\.com$"), re.compile(r"^/([\w-]+)/(\d+)"), ""),
    # Company-subdomain ATSs. Their application form opens from an "Apply" button on the posting page.
    "recruitee": (re.compile(r"^(?P<company>[\w-]+)\.recruitee\.com$"), re.compile(r"^/o/([\w-]+)"), ""),
    "teamtailor": (re.compile(r"^(?P<company>[\w-]+)\.teamtailor\.com$"), re.compile(r"^/jobs/(\d+)"), ""),
    "bamboohr": (re.compile(r"^(?P<company>[\w-]+)\.bamboohr\.com$"), re.compile(r"^/careers/(\d+)"), ""),
    "personio": (
        re.compile(r"^(?P<company>[\w-]+)\.jobs\.personio\.(?:de|com)$"),
        re.compile(r"^/job/(\d+)"),
        "",
    ),
}

# ATSs whose hosted application forms the browser agent can fill. Everything else is manual-apply only.
AUTO_APPLY_ATS = frozenset(_ATS_PATTERNS)

# Domains that host search/listing pages (or need a login) rather than a single applyable form.
AGGREGATOR_HOSTS = (
    "linkedin.com",
    "indeed.",
    "glassdoor.",
    "naukri.com",
    "monster.",
    "ziprecruiter.com",
    "foundit.",
    "shine.com",
    "instahyre.com",
    "cutshort.io",
    "iimjobs.com",
    "hirist.",
    "wellfound.com",
    "builtin.com",
    "simplyhired.",
    "jooble.",
    "talent.com",
    "remoterocketship.com",
    "insightglobal.com",
    "turing.com",
    "careerbuilder.",
    "dice.com",
    "remotive.com",
    "weworkremotely.com",
    "arbeitnow.",
)
_LISTING_PATH_RE = re.compile(r"/(search|jobs/search|job-search)\b|[-/]jobs/?$|/jobs/[\w-]*-jobs/?$", re.I)

# Single-job pages on aggregators: LinkedIn /jobs/view/<id>, Indeed /viewjob?jk=, Naukri /job-listings-<slug>-<id>.
_AGGREGATOR_POSTING_RE = re.compile(
    r"/jobs/view/|viewjob|/job-listings-[\w-]+|/remote-jobs/[\w-]+/[\w-]+-\d+|/jobs/[\w-]+-\d+$"
)

ATS_SEARCH_SITES = ("greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com", "apply.workable.com")


@dataclass(frozen=True)
class AtsInfo:
    name: str  # a key of _ATS_PATTERNS, "aggregator" or "other"
    company_slug: str | None
    job_id: str | None
    is_posting: bool  # URL points at one specific job (not a board index or search page)
    host: str = ""

    @property
    def auto_apply_supported(self) -> bool:
        return self.name in AUTO_APPLY_ATS and self.is_posting


def detect_ats(url: str) -> AtsInfo:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path or "/"
    for name, (host_re, path_re, _) in _ATS_PATTERNS.items():
        host_match = host_re.search(host)
        if not host_match:
            continue
        company = host_match.groupdict().get("company")
        match = path_re.match(path)
        if match is None:
            return AtsInfo(name, company, None, False, host)
        if company:
            return AtsInfo(name, company, match.group(1), True, host)
        return AtsInfo(name, match.group(1), match.group(2), True, host)
    if any(agg in host for agg in AGGREGATOR_HOSTS):
        # Aggregator pages are kept as postings only when they point at a single job.
        single = bool(_AGGREGATOR_POSTING_RE.search(path))
        return AtsInfo("aggregator", None, None, single and not _LISTING_PATH_RE.search(path), host)
    looks_like_posting = bool(re.search(r"/(jobs?|careers?|positions?|openings?|vacanc(y|ies))/[\w-]+", path, re.I))
    return AtsInfo("other", None, None, looks_like_posting and not _LISTING_PATH_RE.search(path), host)


def apply_page_url(url: str) -> str:
    """Return the URL of the application form for ATSs that split description and form."""
    info = detect_ats(url)
    if info.name in _ATS_PATTERNS and info.is_posting:
        suffix = _ATS_PATTERNS[info.name][2]
        base = url.split("?")[0].rstrip("/")
        if suffix and not base.endswith(suffix.rstrip("/")):
            return base + suffix
    return url


def slug_to_company(slug: str) -> str:
    words = re.split(r"[-_.%20]+", slug)
    return " ".join(w.capitalize() for w in words if w) or slug
