import operator
from typing import Annotated, TypedDict

from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.match import JobWithMatch
from ai_service.app.schemas.search import RawJobPosting, SearchQueryRequest


class SearchAgentState(TypedDict, total=False):
    request: SearchQueryRequest
    candidate: CandidateProfile | None
    roles: list[str]
    locations: list[str]
    titles: list[str]  # roles plus related titles suggested from the resume
    queries: list[str]
    raw_postings: list[RawJobPosting]
    verified_postings: list[RawJobPosting]
    results: list[JobWithMatch]
    filtered_out: dict[str, int]
    errors: Annotated[list[str], operator.add]
