from pydantic import BaseModel, Field

from ai_service.app.schemas.job import NormalizedJob


class MatchResult(BaseModel):
    job_id: str
    overall_match: float = Field(..., ge=0, le=100)
    title_match: float = 0.0
    skill_match: float = 0.0
    experience_match: float = 0.0
    location_match: float = 0.0
    sponsorship_match: float = 0.0
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    passed_hard_filters: bool = True
    reasons: list[str] = Field(default_factory=list)


class JobWithMatch(BaseModel):
    job: NormalizedJob
    match: MatchResult | None = None
