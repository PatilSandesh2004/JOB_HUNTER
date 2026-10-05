from fastapi import APIRouter, Depends, HTTPException, status
from ai_service.app.schemas.search import SearchQueryRequest, SearchResponse
from ai_service.app.core.config import settings
from ai_service.app.integrations.search.searxng_client import SearXNGClient
from ai_service.app.services.search.search_service import SearchService
from ai_service.app.agents.search_agent.graph import create_search_graph

router = APIRouter(prefix="/search", tags=["search"])


# Dependency injection provider for SearchService instance.
def get_search_service() -> SearchService:
    client = SearXNGClient(base_url=settings.searxng_url)
    return SearchService(searxng_client=client)


# Search endpoint executing the LangGraph search agent workflow.
@router.post("/", response_model=SearchResponse)
async def execute_job_search(
    request: SearchQueryRequest,
    search_service: SearchService = Depends(get_search_service),
):
    try:
        graph = create_search_graph(search_service=search_service)
        initial_state = {
            "request": request,
            "generated_queries": [],
            "current_query_index": 0,
            "raw_results": [],
            "normalized_results": [],
            "errors": [],
        }
        
        final_state = await graph.ainvoke(initial_state)
        
        return SearchResponse(
            query=", ".join(request.roles),
            total_results=len(final_state["normalized_results"]),
            results=final_state["normalized_results"],
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search execution failed: {str(e)}",
        )
