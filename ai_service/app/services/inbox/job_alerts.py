"""Turn LinkedIn / Indeed / Naukri job-alert emails into job postings.

The alerts are emails the sites send to you, so reading them uses no scraping and no site login. Each job
link is reduced to the site's canonical job URL; the job's title, company and location are read from the
text next to the link. Alert layouts change over time, so the text heuristics are deliberately forgiving:
a job without a recognisable title is skipped rather than guessed.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from email.utils import parseaddr
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger("jobpilot.inbox")

ALERT_SENDERS: dict[str, tuple[str, ...]] = {
    "linkedin": ("linkedin.com",),
    "indeed": ("indeed.com", "indeedemail.com"),
    "naukri": ("naukri.com",),
}
SOURCE_LABEL = {"linkedin": "LinkedIn", "indeed": "Indeed", "naukri": "Naukri"}

_LINKEDIN_JOB_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[\w%-]*?-)?(\d{6,})", re.I)
_NAUKRI_JOB_RE = re.compile(r"naukri\.com/(job-listings-[\w-]+)", re.I)
# Redirect hosts used in alert emails; resolving one is the same request as clicking the link.
_TRACKER_HOSTS = re.compile(r"(^|\.)(click\.naukri\.com|cts\.indeed\.com|click\.indeed\.com|lnkd\.in)$", re.I)
_BOILERPLATE_RE = re.compile(
    r"^(apply( now)?|easy apply|quick apply|view( this)? job|view details|see (the )?job|see all( jobs)?|view all.*|"
    r"new|promoted|actively recruiting|be an early applicant|save|share|unsubscribe|manage alerts?|"
    r"just (now|posted)|today|\d+\+?\s*(minute|hour|day|week|month)s?( ago)?|\d+ (applicants?|connections?).*|"
    r".*\bjobs? (alerts?|for you|you may be interested in)\b.*|top (job )?picks?.*|"
    r"(₹|\$|€|£|inr|usd).*|.*\b(lpa|lakhs?|salary)\b.*|\d+\s*-\s*\d+\s*yrs?.*|"
    r"responds? (quickly|within).*|.*\brating\b.*|\d(\.\d)?\s*★?)$",
    re.I,
)
_LOCATION_HINT_RE = re.compile(
    r",|\b(remote|hybrid|on-?site|india|bengaluru|bangalore|hyderabad|pune|chennai|mumbai|delhi|noida|gurugram|"
    r"gurgaon|kolkata|ahmedabad)\b",
    re.I,
)


@dataclass
class AlertJob:
    url: str
    title: str
    company: str | None
    location: str | None


def alert_source(sender: str) -> str | None:
    """'linkedin' | 'indeed' | 'naukri' when the email comes from that site's alert system."""
    domain = parseaddr(sender)[1].lower().rpartition("@")[2]
    for source, domains in ALERT_SENDERS.items():
        if any(domain == d or domain.endswith("." + d) for d in domains):
            return source
    return None


def canonical_job_url(source: str, url: str) -> str | None:
    """The site's plain job URL for a link in its alert email, without tracking parameters."""
    if source == "linkedin":
        match = _LINKEDIN_JOB_RE.search(url)
        return f"https://www.linkedin.com/jobs/view/{match.group(1)}" if match else None
    if source == "naukri":
        match = _NAUKRI_JOB_RE.search(url)
        return f"https://www.naukri.com/{match.group(1)}" if match else None
    if source == "indeed":
        parsed = urlparse(url)
        if not (parsed.hostname or "").endswith("indeed.com"):
            return None
        job_key = (parse_qs(parsed.query).get("jk") or parse_qs(parsed.query).get("vjk") or [""])[0]
        if not re.fullmatch(r"[0-9a-f]{10,20}", job_key):
            return None
        host = parsed.hostname if not _TRACKER_HOSTS.search(parsed.hostname or "") else "www.indeed.com"
        return f"https://{host}/viewjob?jk={job_key}"
    return None


def is_tracking_link(url: str) -> bool:
    return bool(_TRACKER_HOSTS.search(urlparse(url).hostname or ""))


class _Tokens(HTMLParser):
    """Flatten an HTML email into text and link tokens, in reading order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[tuple[str, str, str]] = []  # (kind, href, text) kind = "link" | "text"
        self._href: str | None = None
        self._text: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head", "title"):
            self._skip += 1
        elif tag == "a":
            self._flush()
            self._href = dict(attrs).get("href") or ""
        elif tag in ("br", "p", "div", "td", "tr", "li", "table", "h1", "h2", "h3", "h4", "span"):
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a":
            self._flush()
            self._href = None
        elif tag in ("p", "div", "td", "tr", "li", "table", "h1", "h2", "h3", "h4", "span"):
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._text.append(data)

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._text)).strip()
        self._text = []
        if self._href is not None:
            self.tokens.append(("link", self._href, text))
        elif text:
            self.tokens.append(("text", "", text))

    def close(self):
        super().close()
        self._flush()


def _meaningful(text: str) -> bool:
    text = text.strip(" ·•|-–—")
    return 2 <= len(text) <= 120 and not _BOILERPLATE_RE.match(text)


def _tokens(html: str, text: str) -> list[tuple[str, str, str]]:
    if html:
        parser = _Tokens()
        parser.feed(html)
        parser.close()
        return parser.tokens
    # Plain-text alerts put a job's lines first and its URL last ("Title / Company / City / View job: URL").
    # Emit each URL ahead of the lines that preceded it, so they read like the HTML layout: link, then details.
    tokens: list[tuple[str, str, str]] = []
    block: list[str] = []
    for line in (line.strip() for line in text.splitlines()):
        urls = re.findall(r"https?://\S+", line)
        stripped = re.sub(r"https?://\S+", "", line).strip(" :")
        if stripped and not urls:
            block.append(stripped)
        for url in urls:
            tokens.append(("link", url.rstrip(">)."), ""))
            tokens += [("text", "", t) for t in block]
            block = []
    return tokens


async def parse_job_alert(
    source: str, html: str, text: str, resolve: httpx.AsyncClient | None = None
) -> list[AlertJob]:
    """Jobs listed in one alert email. With `resolve`, tracking redirects are followed to the job URL."""
    tokens = _tokens(html, text)
    links = {href for kind, href, _ in tokens if kind == "link"}
    resolved = {href: canonical_job_url(source, href) for href in links}
    if resolve is not None:
        pending = [href for href, url in resolved.items() if url is None and is_tracking_link(href)]
        targets = await asyncio.gather(*(_follow(resolve, href) for href in pending))
        resolved |= {
            href: canonical_job_url(source, target) if target else None
            for href, target in zip(pending, targets, strict=True)
        }

    jobs: dict[str, AlertJob] = {}
    for index, (kind, href, label) in enumerate(tokens):
        url = resolved.get(href) if kind == "link" else None
        if not url:
            continue
        # The link text is usually the title; company and location follow it.
        following: list[str] = []
        for next_kind, next_href, next_text in tokens[index + 1 : index + 8]:
            if next_kind == "link" and resolved.get(next_href) and resolved.get(next_href) != url:
                break  # the next job starts
            if _meaningful(next_text):
                following.append(next_text.strip(" ·•|-–—"))
        texts = ([label.strip(" ·•|-–—")] if _meaningful(label) else []) + following
        texts = list(dict.fromkeys(texts))
        if not texts:
            continue
        title, rest = texts[0], texts[1:]
        company = rest[0] if rest else None
        location = next((t for t in rest[1:3] if _LOCATION_HINT_RE.search(t)), None)
        if company and _LOCATION_HINT_RE.search(company) and "," in company and len(rest) == 1:
            company, location = None, company
        found = AlertJob(url=url, title=title, company=company, location=location)
        current = jobs.get(url)
        # Image link + text link for the same job: keep the richer one.
        if current is None or _richness(found) > _richness(current):
            jobs[url] = found
    return list(jobs.values())


def _richness(job: AlertJob) -> int:
    return bool(job.company) + bool(job.location) + (len(job.title) > 3)


async def _follow(client: httpx.AsyncClient, url: str, hops: int = 4) -> str | None:
    """Follow redirects by hand (HEAD, falling back to GET) without downloading the final page."""
    current = url
    for _ in range(hops):
        try:
            response = await client.head(current, follow_redirects=False)
            if response.status_code == 405:
                response = await client.get(current, follow_redirects=False)
        except httpx.HTTPError as exc:
            logger.info("Could not resolve alert link: %s", exc)
            return None
        location = response.headers.get("location")
        if not response.is_redirect or not location:
            return current
        current = str(response.url.join(location))
    return current
