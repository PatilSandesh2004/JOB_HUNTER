"""Resume-to-job similarity with a small local embedding model (no API calls, runs on the CPU).

Catches fit that keywords miss ("built LLM agents" vs "agentic workflows"). The model (BAAI/bge-small-en-v1.5,
about 65 MB) is downloaded once into data/models when the service starts; until it is ready, or if it cannot
be loaded, scores are simply left out and the rest of the match is unaffected.
"""

import asyncio
import hashlib
import logging
from collections import OrderedDict
from typing import Any

from ai_service.app.core.config import Settings, settings
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob

logger = logging.getLogger("jobpilot.semantic")

MIN_DESCRIPTION = 200  # shorter postings say too little to compare
TEXT_LIMIT = 2000  # the model reads ~512 tokens; the start of a posting carries the role and requirements
# Cosine similarity of bge-small between a resume and job descriptions: ~0.6 unrelated, ~0.88 same work.
LOW, HIGH = 0.60, 0.88
CACHE_SIZE = 5000


def resume_text(candidate: CandidateProfile) -> str:
    parts = [candidate.current_role or "", candidate.summary or "", "Skills: " + ", ".join(candidate.skills[:40])]
    parts += [f"{w.title} at {w.company}. {(w.description or '')[:600]}" for w in candidate.work_experience[:4]]
    return "\n".join(p for p in parts if p.strip())[:TEXT_LIMIT]


def job_text(job: NormalizedJob) -> str:
    return f"{job.title}. {job.description}"[:TEXT_LIMIT]


def calibrate(cosine: float) -> float:
    return round(max(0.0, min(1.0, (cosine - LOW) / (HIGH - LOW))) * 100, 1)


class SemanticMatcher:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config
        self._model: Any = None
        self._status = "off" if not config.semantic_matching else "not loaded"
        self._loading: asyncio.Task | None = None
        self._cache: OrderedDict[str, Any] = OrderedDict()

    @property
    def status(self) -> str:
        """off | not loaded | loading | ready | unavailable (model could not be loaded)"""
        return self._status

    @property
    def ready(self) -> bool:
        return self._model is not None

    async def warm_up(self) -> None:
        """Load (and on first use download) the model in a worker thread. Never raises."""
        if not self.config.semantic_matching or self._model is not None:
            return
        if self._loading is None:
            self._loading = asyncio.ensure_future(self._load())
        await self._loading

    async def _load(self) -> None:
        self._status = "loading"
        try:
            self._model = await asyncio.to_thread(self._create_model)
            self._status = "ready"
            logger.info("Semantic matching ready (%s)", self.config.semantic_model)
        except Exception as exc:  # missing package, no network for the first download, broken cache
            self._status = "unavailable"
            logger.warning("Semantic matching unavailable, scoring without it: %s", exc)

    def _create_model(self) -> Any:
        from fastembed import TextEmbedding

        cache = self.config.data_dir / "models"
        cache.mkdir(parents=True, exist_ok=True)
        return TextEmbedding(self.config.semantic_model, cache_dir=str(cache))

    async def scores(self, candidate: CandidateProfile, jobs: list[NormalizedJob]) -> dict[str, float]:
        """job id -> 0-100 similarity to the resume, for jobs with enough description. Empty when not ready."""
        if self._model is None:
            return {}
        comparable = [j for j in jobs if len(j.description or "") >= MIN_DESCRIPTION]
        if not comparable:
            return {}
        texts = {job.id: job_text(job) for job in comparable}
        resume = resume_text(candidate)
        vectors = await asyncio.to_thread(self._vectors, [resume, *texts.values()])
        mine = vectors[0]
        return {job_id: calibrate(_cosine(mine, vector)) for job_id, vector in zip(texts, vectors[1:], strict=True)}

    def _vectors(self, texts: list[str]) -> list[Any]:
        keys = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in texts]
        missing = [(k, t) for k, t in zip(keys, texts, strict=True) if k not in self._cache]
        if missing:
            for (key, _), vector in zip(missing, self._model.embed([t for _, t in missing]), strict=True):
                self._cache[key] = vector
                if len(self._cache) > CACHE_SIZE:
                    self._cache.popitem(last=False)
        for key in keys:
            self._cache.move_to_end(key)
        return [self._cache[k] for k in keys]


def _cosine(a: Any, b: Any) -> float:
    import numpy as np

    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator else 0.0
