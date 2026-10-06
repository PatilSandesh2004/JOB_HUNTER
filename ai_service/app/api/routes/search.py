from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.agents.search_agent.graph import SearchAgent
from ai_service.app.api.deps import get_notifier, get_search_agent
from ai_service.app.database.session import get_db
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.search import SearchQueryRequest, SearchResponse
from ai_service.app.services.notifications.webhook_service import WebhookNotificationService

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search_jobs(
    request: SearchQueryRequest,
    db: AsyncSession = Depends(get_db),
    agent: SearchAgent = Depends(get_search_agent),
    notifier: WebhookNotificationService = Depends(get_notifier),
) -> SearchResponse:
    """Discover, normalise, de-duplicate and rank jobs against the active profile, then persist them."""
    candidate = await CandidateRepository(db).get_active()
    response = await agent.run(request, candidate)
    await JobRepository(db).upsert_many(response.results)
    await notifier.notify_high_matches(response.results)
    return response
