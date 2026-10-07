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
    semantic_match: float | None = Field(default=None, description="Resume-to-description similarity, when computed")
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list, description="Required skills not in your profile")
    missing_preferred: list[str] = Field(default_factory=list, description="Nice-to-have skills not in your profile")
    passed_hard_filters: bool = True
    confidence: str = Field(default="MEDIUM", description="HIGH / MEDIUM / LOW: how much the posting told us")
    ai_verdict: str | None = Field(default=None, description="strong / possible / weak / no, from the AI review")
    ai_reason: str | None = None
    ai_profile: str | None = Field(default=None, description="Profile version the AI verdict was given for")
    reasons: list[str] = Field(default_factory=list)


class JobWithMatch(BaseModel):
    job: NormalizedJob
    match: MatchResult | None = None
