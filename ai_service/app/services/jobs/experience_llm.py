"""Experience requirements the regex parser could not read, extracted by the LLM in one batched call.

Used only when the user picked an experience range: a posting with unknown experience is otherwise kept
blindly, which is how "5+ years" jobs slipped into a 1-3 search. Answers are cached per job and must quote
the posting, so the model cannot invent a number.
"""

import json
import logging
import time

from ai_service.app.core.errors import LLMUnavailableError
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.schemas.job import NormalizedJob

logger = logging.getLogger("jobpilot.experience_llm")

MAX_JOBS = 20
MIN_DESCRIPTION = 200  # shorter texts rarely state experience; not worth a call
CACHE_SECONDS = 24 * 3600

_SYSTEM = (
    "You read job postings and extract the years of professional experience the employer REQUIRES. "
    "Only use numbers written in the posting. Ignore company age, years of a product, nice-to-have "
    "bars and experience with single tools when an overall requirement exists. If the posting states "
    "no requirement, return null for both numbers. Respond with a JSON object only."
)
_USER = """For each posting, return the required experience.

POSTINGS
{postings}

Return {{"jobs": [{{"id": <id>, "min_years": <number or null>, "max_years": <number or null>, "quote": <the words from the posting that state it, or null>}}, ...]}}."""


class ExperienceExtractor:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self._cache: dict[str, tuple[float, tuple[float | None, float | None]]] = {}

    async def fill_unknown(self, jobs: list[NormalizedJob]) -> int:
        """Set experience on jobs that have none, in place. Returns how many were filled."""
        if not self.llm.available:
            return 0
        now = time.monotonic()
        filled = 0
        pending: list[NormalizedJob] = []
        for job in jobs:
            if job.experience_required is not None or len(job.description or "") < MIN_DESCRIPTION:
                continue
            cached = self._cache.get(job.id)
            if cached and now - cached[0] < CACHE_SECONDS:
                filled += _apply(job, cached[1])
            elif len(pending) < MAX_JOBS:
                pending.append(job)
        if not pending:
            return filled

        listed = [{"id": i, "title": j.title, "text": (j.description or "")[:1800]} for i, j in enumerate(pending)]
        try:
            data = await self.llm.complete_json(
                _SYSTEM,
                _USER.format(postings=json.dumps(listed, ensure_ascii=False)),
                temperature=0.0,
                max_tokens=1500,
            )
        except LLMUnavailableError as exc:
            logger.warning("Experience extraction skipped: %s", exc)
            return filled

        for item in data.get("jobs") or []:
            if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                continue
            if not 0 <= item["id"] < len(pending):
                continue
            job = pending[item["id"]]
            low, high = _number(item.get("min_years")), _number(item.get("max_years"))
            quote = item.get("quote")
            # The quote must really be in the posting, and contain the number.
            if low is not None and not (
                isinstance(quote, str) and quote.strip() and quote.strip().lower() in (job.description or "").lower()
            ):
                low = high = None
            if high is not None and (low is None or high < low):
                high = None
            self._cache[job.id] = (now, (low, high))
            filled += _apply(job, (low, high))
        return filled


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if 0 <= value <= 25 else None


def _apply(job: NormalizedJob, years: tuple[float | None, float | None]) -> int:
    if years[0] is None:
        return 0
    job.experience_required, job.experience_max = years
    return 1
