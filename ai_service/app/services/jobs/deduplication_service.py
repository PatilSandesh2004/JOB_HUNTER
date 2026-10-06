"""Remove duplicate postings: exact canonical URL first, then fuzzy title+company similarity."""

from rapidfuzz import fuzz

from ai_service.app.schemas.job import NormalizedJob


class JobDeduplicationService:
    def deduplicate(self, jobs: list[NormalizedJob], similarity_threshold: float = 92.0) -> list[NormalizedJob]:
        unique: list[NormalizedJob] = []
        seen_ids: set[str] = set()
        seen_keys: list[str] = []

        for job in jobs:
            if job.id in seen_ids:
                continue
            key = f"{job.title} {job.company}".lower()
            # Fuzzy matching only makes sense when we actually know the company.
            if job.company != "Unknown company" and any(
                fuzz.token_sort_ratio(key, other) >= similarity_threshold for other in seen_keys
            ):
                continue
            seen_ids.add(job.id)
            seen_keys.append(key)
            unique.append(job)
        return unique
