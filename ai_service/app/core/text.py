"""Small text helpers for data from the open web: HTML to text, broken encodings, dates."""

import html
import re
from datetime import UTC, datetime, timedelta
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_RELATIVE_RE = re.compile(r"(\d+|an?|one)\s+(minute|min|hour|hr|day|week|month)s?\s+ago", re.I)
_UNITS = {"minute": "minutes", "min": "minutes", "hour": "hours", "hr": "hours", "day": "days", "week": "weeks"}


def strip_html(text: str | None, limit: int = 4000) -> str:
    # Unescape before stripping: some APIs (Greenhouse) return HTML-escaped HTML ("&lt;p&gt;").
    unescaped = html.unescape(text or "")
    cleaned = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", unescaped))).strip()
    return fix_mojibake(cleaned)[:limit]


def fix_mojibake(text: str) -> str:
    """Repair UTF-8 text that was decoded as Latin-1 somewhere upstream ("weâ€™re" -> "we're")."""
    if "â" not in text and "Ã" not in text:
        return text
    for codec in ("cp1252", "latin-1"):
        try:
            return text.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text


def parse_datetime(value: Any, now: datetime | None = None) -> datetime | None:
    """ISO strings, Unix seconds or milliseconds, and relative text like "3 days ago" (Google results)."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, int | float):
            if value <= 0:
                return None
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=UTC)
        text = str(value).strip()
        relative = _RELATIVE_RE.search(text)
        if relative:
            amount = 1 if relative.group(1).lower() in ("a", "an", "one") else int(relative.group(1))
            unit = relative.group(2).lower()
            delta = timedelta(days=30 * amount) if unit == "month" else timedelta(**{_UNITS[unit]: amount})
            return (now or datetime.now(UTC)) - delta
        text = text.replace("Z", "+00:00").replace(" UTC", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, OSError, OverflowError):
        return None
