from typing import List, Optional
from pydantic import BaseModel, Field


# Pydantic BaseModel ensures strict type checking, data validation, and automatic serialization.
class SearchQueryRequest(BaseModel):
    roles: List[str] = Field(..., description="Target job roles or titles")
    locations: List[str] = Field(default_factory=list, description="Target locations or cities")
    remote_only: bool = Field(default=False, description="Filter for remote positions only")
    sponsorship_required: bool = Field(default=False, description="Filter for visa sponsorship requirement")


# Schema representing a normalized single search result from any search provider.
class SearchResultItem(BaseModel):
    title: str
    url: str
    content: Optional[str] = None
    engine: Optional[str] = None


# Schema representing the structured HTTP search response returned by the search API.
class SearchResponse(BaseModel):
    query: str
    total_results: int
    results: List[SearchResultItem]
