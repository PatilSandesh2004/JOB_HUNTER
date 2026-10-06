"""Decide whether a job's location fits the places a user asked for.

"Bengaluru" matches Bengaluru/Bangalore postings. "Remote" additionally accepts remote roles that are
open worldwide or to the user's country, and rejects remote roles restricted to other countries.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum

from ai_service.app.schemas.job import NormalizedJob, RemoteScope, WorkplaceType

# canonical city -> (aliases, country)
CITIES: dict[str, tuple[tuple[str, ...], str]] = {
    "bengaluru": (("bengaluru", "bangalore", "blr"), "india"),
    "hyderabad": (("hyderabad", "secunderabad"), "india"),
    "pune": (("pune",), "india"),
    "chennai": (("chennai", "madras"), "india"),
    "mumbai": (("mumbai", "bombay", "navi mumbai", "thane"), "india"),
    "delhi": (("delhi", "new delhi", "ncr", "delhi ncr"), "india"),
    "gurugram": (("gurugram", "gurgaon"), "india"),
    "noida": (("noida", "greater noida"), "india"),
    "kolkata": (("kolkata", "calcutta"), "india"),
    "ahmedabad": (("ahmedabad",), "india"),
    "kochi": (("kochi", "cochin"), "india"),
    "thiruvananthapuram": (("thiruvananthapuram", "trivandrum"), "india"),
    "coimbatore": (("coimbatore",), "india"),
    "jaipur": (("jaipur",), "india"),
    "mysuru": (("mysuru", "mysore"), "india"),
    "london": (("london",), "united kingdom"),
    "berlin": (("berlin",), "germany"),
    "singapore": (("singapore",), "singapore"),
    "dubai": (("dubai",), "united arab emirates"),
    "toronto": (("toronto",), "canada"),
    "new york": (("new york", "nyc"), "united states"),
    "san francisco": (("san francisco", "sf bay area", "bay area"), "united states"),
}
# country -> aliases that may appear in location strings
# Ambiguous two-letter codes ("in", "de", "ca") are deliberately left out: "Remote in Europe" is not India.
COUNTRIES: dict[str, tuple[str, ...]] = {
    "india": ("india",),
    "united states": ("united states", "usa", "us", "u.s.", "u.s.a.", "america"),
    "united kingdom": ("united kingdom", "uk", "england", "great britain"),
    "germany": ("germany", "deutschland"),
    "canada": ("canada",),
    "singapore": ("singapore",),
    "united arab emirates": ("united arab emirates", "uae"),
    "australia": ("australia",),
    "netherlands": ("netherlands",),
}
# Region words that include a country.
REGIONS: dict[str, tuple[str, ...]] = {
    "india": ("apac", "asia", "asia pacific", "south asia"),
    "singapore": ("apac", "asia", "asia pacific"),
    "germany": ("europe", "eu", "emea"),
    "netherlands": ("europe", "eu", "emea"),
    "united kingdom": ("europe", "emea"),
    "united states": ("americas", "north america"),
    "canada": ("americas", "north america"),
}
_SCOPE_COUNTRIES: dict[RemoteScope, set[str]] = {
    RemoteScope.US_ONLY: {"united states"},
    RemoteScope.UK_ONLY: {"united kingdom"},
    RemoteScope.EU_ONLY: {"germany", "netherlands"},
    RemoteScope.INDIA_ONLY: {"india"},
    RemoteScope.ASIA: {"india", "singapore"},
}
_ANYWHERE = re.compile(r"\b(worldwide|anywhere|global(ly)?|international|any location)\b", re.I)
_GENERIC_REMOTE = re.compile(r"^\W*(fully\s+)?(remote|wfh|work from home|unknown|n/?a|flexible)?\W*$", re.I)


class LocationFit(StrEnum):
    MATCH = "MATCH"  # in one of the requested places
    REMOTE_OK = "REMOTE_OK"  # remote and open to the user
    UNKNOWN = "UNKNOWN"  # posting does not say where
    MISMATCH = "MISMATCH"  # somewhere else, or remote but restricted to other countries


def _contains(text: str, alias: str) -> bool:
    return re.search(rf"(?<![\w.]){re.escape(alias)}(?![\w])", text) is not None


@dataclass
class LocationMatcher:
    places: list[str]
    remote_ok: bool = False
    aliases: set[str] = field(default_factory=set)
    countries: set[str] = field(default_factory=set)

    @classmethod
    def from_preferences(cls, locations: list[str]) -> "LocationMatcher":
        matcher = cls(places=[])
        for raw in locations:
            place = raw.strip().lower()
            if not place:
                continue
            if place in {"remote", "anywhere", "worldwide", "wfh"}:
                matcher.remote_ok = True
                continue
            matcher.places.append(place)
            city = next((c for c, (aliases, _) in CITIES.items() if any(_contains(place, a) for a in aliases)), None)
            country = next((c for c, aliases in COUNTRIES.items() if any(_contains(place, a) for a in aliases)), None)
            if city:
                matcher.aliases.update(CITIES[city][0])
                matcher.countries.add(CITIES[city][1])
            elif country:
                # A whole country: accept the country name and all its known cities.
                matcher.aliases.update(COUNTRIES[country])
                matcher.aliases.update(a for aliases, c in CITIES.values() if c == country for a in aliases)
                matcher.countries.add(country)
            else:
                matcher.aliases.add(place.split(",")[0].strip())
        return matcher

    @property
    def active(self) -> bool:
        return bool(self.places or self.remote_ok)

    def fit(self, job: NormalizedJob) -> LocationFit:
        return self.fit_values(job.location, job.title, job.workplace_type == WorkplaceType.REMOTE, job.remote_scope)

    def fit_values(
        self, location: str | None, title: str, is_remote: bool, remote_scope: RemoteScope = RemoteScope.UNKNOWN
    ) -> LocationFit:
        location = (location or "").lower()
        text = f"{location} | {title.lower()}"
        if any(_contains(text, alias) for alias in self.aliases):
            return LocationFit.MATCH

        known_location = bool(location) and not _GENERIC_REMOTE.match(location)
        is_remote = is_remote or (bool(location) and re.search(r"\bremote\b", location) is not None)
        if is_remote:
            if not self.remote_ok:
                return LocationFit.MISMATCH if known_location else LocationFit.UNKNOWN
            scope_countries = _SCOPE_COUNTRIES.get(remote_scope)
            if scope_countries is not None and self.countries and not scope_countries & self.countries:
                return LocationFit.MISMATCH  # snippet said e.g. "Remote (US only)"
            if not known_location or _ANYWHERE.search(location) or self._mentions_own_country(location):
                return LocationFit.REMOTE_OK
            return LocationFit.MISMATCH  # e.g. "Remote - US", "Lithuania"
        if known_location:
            return LocationFit.MISMATCH
        return LocationFit.UNKNOWN

    def _mentions_own_country(self, location: str) -> bool:
        for country in self.countries:
            words = (*COUNTRIES.get(country, (country,)), *REGIONS.get(country, ()))
            if any(_contains(location, w) for w in words):
                return True
        return False
