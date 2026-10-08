"""Remove duplicate postings: the same URL, or the same title at the same company in the same place.

Companies often post one opening per city ("AI Engineer" in Bengaluru and in Toronto). Those are different
jobs, so the place is part of the comparison; a copy with an unknown place (a search snippet) merges with
the copy that states it. Of each set of duplicates the most informative copy is kept.
"""

import re

from rapidfuzz import fuzz

from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.services.jobs.location_service import CITIES

_UNKNOWN_PLACES = {"", "unknown", "n/a", "na", "anywhere"}


def _place(location: str) -> str:
    """'Bangalore, Karnataka, India' -> 'bengaluru'; 'Remote - India' -> 'remote'; 'Unknown' -> ''."""
    text = (location or "").lower()
    for city, (aliases, _) in CITIES.items():
        if any(re.search(rf"(?<![\w.]){re.escape(a)}(?![\w])", text) for a in aliases):
            return city
    if re.search(r"\bremote\b", text):
        return "remote"
    first = re.split(r"[,;|/-]", text)[0].strip()
    return "" if first in _UNKNOWN_PLACES else first


def _richness(job: NormalizedJob) -> tuple:
    return (job.verified, job.posted_at is not None, _place(job.location) != "", len(job.description or ""))


class JobDeduplicationService:
    def deduplicate(self, jobs: list[NormalizedJob], similarity_threshold: float = 92.0) -> list[NormalizedJob]:
        groups: list[list[NormalizedJob]] = []
        keys: list[tuple[str, str]] = []  # (title + company, place) of each group's first job
        group_of_id: dict[str, int] = {}

        for job in jobs:
            if job.id in group_of_id:
                groups[group_of_id[job.id]].append(job)
                continue
            key, place = f"{job.title} {job.company}".lower(), _place(job.location)
            found = None
            # Fuzzy matching only makes sense when we actually know the company.
            if job.company != "Unknown company":
                for index, (other_key, other_place) in enumerate(keys):
                    same_place = place == other_place or not place or not other_place
                    if same_place and fuzz.token_sort_ratio(key, other_key) >= similarity_threshold:
                        found = index
                        break
            if found is None:
                found = len(groups)
                groups.append([])
                keys.append((key, place))
            groups[found].append(job)
            group_of_id[job.id] = found
        return [max(group, key=_richness) for group in groups]
