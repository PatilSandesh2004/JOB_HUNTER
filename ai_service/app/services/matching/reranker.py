"""Re-ranking of the best matches with a small local cross-encoder (no API calls, runs on the CPU).

The embedding model in semantic.py compares the resume and a posting separately; a cross-encoder reads the
search ("Machine Learning Engineer, 2-3 years, Python PyTorch") and the posting together, so it judges how well
the posting answers the search much more precisely. It is slower, so only the top results are re-ranked.
The model (Xenova/ms-marco-MiniLM-L-6-v2, about 80 MB) is downloaded once into data/models when the service
starts; until it is ready, or if it cannot be loaded, results keep their rule-based order.
"""

import asyncio
import hashlib
import logging
import math
from collections import OrderedDict
from typing import Any

from ai_service.app.core.config import Settings, settings
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.schemas.match import MatchResult

logger = logging.getLogger("jobpilot.reranker")

TEXT_LIMIT = 1200  # the model reads 512 tokens; the start of a posting carries the role and requirements
WEIGHT = 0.2  # share of the final score taken by the re-ranker
# ms-marco logits run from about -11 (unrelated) to +11; a plain sigmoid puts related roles ("Data Engineer" for
# an ML search) next to unrelated ones at ~0, so the logits are softened to spread them across 0-100.
TEMPERATURE = 4.0
CACHE_SIZE = 5000


def search_query(roles: list[str], experience: str | None, candidate: CandidateProfile | None) -> str:
    """The search as one sentence: roles, the wanted years and the candidate's strongest skills."""
    parts = [" / ".join(roles)]
    if experience and experience != "ANY":
        parts.append(f"{experience} years of experience")
    if candidate is not None and candidate.skills:
        parts.append(", ".join(candidate.skills[:6]))
    return ", ".join(p for p in parts if p)


def job_text(job: NormalizedJob) -> str:
    return f"{job.title} at {job.company}. {job.description or ''}"[:TEXT_LIMIT]


def apply_rerank(match: MatchResult, score: float) -> MatchResult:
    """Blend the re-ranker's 0-100 relevance into the score. A job that failed a hard filter stays capped."""
    overall = match.overall_match
    if match.passed_hard_filters:
        overall = (1 - WEIGHT) * overall + WEIGHT * score
    return match.model_copy(
        update={
            "overall_match": round(max(0.0, min(100.0, overall)), 1),
            "rerank_match": round(score, 1),
            "reasons": [*match.reasons, f"Relevance to your search: {score:.0f}%"],
        }
    )


class Reranker:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config
        self.top_n = config.reranker_top_n
        self._model: Any = None
        self._status = "off" if not config.reranker_enabled else "not loaded"
        self._loading: asyncio.Task | None = None
        self._cache: OrderedDict[str, float] = OrderedDict()

    @property
    def status(self) -> str:
        """off | not loaded | loading | ready | unavailable (model could not be loaded)"""
        return self._status

    @property
    def ready(self) -> bool:
        return self._model is not None

    async def warm_up(self) -> None:
        """Load (and on first use download) the model in a worker thread. Never raises."""
        if not self.config.reranker_enabled or self._model is not None:
            return
        if self._loading is None:
            self._loading = asyncio.ensure_future(self._load())
        await self._loading

    async def _load(self) -> None:
        self._status = "loading"
        try:
            self._model = await asyncio.to_thread(self._create_model)
            self._status = "ready"
            logger.info("Re-ranker ready (%s)", self.config.reranker_model)
        except Exception as exc:  # missing package, no network for the first download, broken cache
            self._status = "unavailable"
            logger.warning("Re-ranker unavailable, ranking without it: %s", exc)

    def _create_model(self) -> Any:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        cache = self.config.data_dir / "models"
        cache.mkdir(parents=True, exist_ok=True)
        return TextCrossEncoder(self.config.reranker_model, cache_dir=str(cache))

    async def scores(self, query: str, jobs: list[NormalizedJob]) -> dict[str, float]:
        """job id -> 0-100 relevance to the query. Empty when the model is not ready."""
        if self._model is None or not jobs or not query:
            return {}
        texts = {job.id: job_text(job) for job in jobs}
        try:
            values = await asyncio.to_thread(self._scores, query, list(texts.values()))
        except Exception as exc:  # never fail a search because of the re-ranker
            logger.warning("Re-ranking skipped: %s", exc)
            return {}
        return dict(zip(texts, values, strict=True))

    def _scores(self, query: str, texts: list[str]) -> list[float]:
        keys = [hashlib.sha1(f"{query}\n{t}".encode()).hexdigest() for t in texts]
        missing = [(k, t) for k, t in zip(keys, texts, strict=True) if k not in self._cache]
        if missing:
            logits = self._model.rerank(query, [t for _, t in missing])
            for (key, _), logit in zip(missing, logits, strict=True):
                self._cache[key] = 100.0 / (1.0 + math.exp(-float(logit) / TEMPERATURE))
                if len(self._cache) > CACHE_SIZE:
                    self._cache.popitem(last=False)
        for key in keys:
            self._cache.move_to_end(key)
        return [self._cache[k] for k in keys]
