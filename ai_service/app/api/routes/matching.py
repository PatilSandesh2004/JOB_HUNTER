from typing import List
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, status
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.services.matching.matching_engine import MatchingEngineService, MatchResult

router = APIRouter(prefix="/matching", tags=["matching"])


class MatchRequest(BaseModel):
    candidate: CandidateProfile
    jobs: List[NormalizedJob]


@router.post("/", response_model=List[MatchResult])
async def match_candidate_jobs(request: MatchRequest):
    try:
        service = MatchingEngineService()
        results = []
        for job in request.jobs:
            res = service.evaluate_match(candidate=request.candidate, job=job)
            results.append(res)
        return sorted(results, key=lambda x: x.overall_match, reverse=True)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Matching calculation failed: {str(e)}",
        )
