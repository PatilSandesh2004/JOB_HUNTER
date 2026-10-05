from typing import Any, Dict, List, TypedDict, Optional
from ai_service.app.schemas.search import SearchQueryRequest, SearchResultItem


# LangGraph state typed dictionary tracking the workflow execution state.
class SearchAgentState(TypedDict):
    request: SearchQueryRequest
    generated_queries: List[str]
    current_query_index: int
    raw_results: List[Dict[str, Any]]
    normalized_results: List[SearchResultItem]
    errors: List[str]
