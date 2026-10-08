import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.agents.search_agent.graph import SearchAgent
from ai_service.app.api.deps import get_notifier, get_search_agent
from ai_service.app.database.session import AsyncSessionLocal, get_db
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.search import SearchProgress, SearchQueryRequest, SearchResponse
from ai_service.app.services.matching.feedback import FeedbackModel
from ai_service.app.services.notifications.alerts import MatchAlertService

logger = logging.getLogger("jobpilot.search")

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search_jobs(
    request: SearchQueryRequest,
    db: AsyncSession = Depends(get_db),
    agent: SearchAgent = Depends(get_search_agent),
    notifier: MatchAlertService = Depends(get_notifier),
) -> SearchResponse:
    """Discover, normalise, de-duplicate and rank jobs against the active profile, then persist them."""
    candidate = await CandidateRepository(db).get_active()
    response = await agent.run(request, candidate, await FeedbackModel.load(db))
    repo = JobRepository(db)
    await repo.upsert_many(response.results, checked=True)
    _drop_hidden(response, await repo.hidden_ids([r.job.id for r in response.results]))
    await notifier.notify_new(db, response.results)
    return response


@router.post("/stream", response_class=StreamingResponse)
async def search_jobs_stream(
    request: SearchQueryRequest,
    agent: SearchAgent = Depends(get_search_agent),
    notifier: MatchAlertService = Depends(get_notifier),
) -> StreamingResponse:
    """Same as `POST /search`, streamed as Server-Sent Events.

    Emits `stage` events (`{stage, label, detail}`) as each step finishes, then one `result` event with the
    SearchResponse, or an `error` event (`{detail}`) if the search fails part-way.
    """
    async with AsyncSessionLocal() as session:
        candidate = await CandidateRepository(session).get_active()
        feedback = await FeedbackModel.load(session)
    state = agent.initial_state(request, candidate, feedback)  # invalid input -> 400 before the stream starts

    async def events() -> AsyncIterator[str]:
        try:
            async for item in agent.stream(state):
                if isinstance(item, SearchProgress):
                    yield _sse("stage", item.model_dump_json())
                    continue
                async with AsyncSessionLocal() as session:
                    repo = JobRepository(session)
                    await repo.upsert_many(item.results, checked=True)
                    _drop_hidden(item, await repo.hidden_ids([r.job.id for r in item.results]))
                    await notifier.notify_new(session, item.results)
                yield _sse("result", item.model_dump_json())
        except Exception as exc:
            logger.exception("Streamed search failed")
            yield _sse("error", json.dumps({"detail": f"Search failed: {exc}"}))

    # X-Accel-Buffering stops reverse proxies (nginx) from holding events back.
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


def _drop_hidden(response: SearchResponse, hidden: set[str]) -> None:
    """Jobs you marked "not interested" stay stored (so they stay hidden) but are not shown again."""
    if not hidden:
        return
    response.results = [r for r in response.results if r.job.id not in hidden]
    response.total_results = len(response.results)
    response.filtered_out["not interested"] = len(hidden)


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"
