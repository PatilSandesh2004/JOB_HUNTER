from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from ai_service.app.schemas.match import JobWithMatch


class SearchQueryRequest(BaseModel):
    roles: list[str] = Field(
        default_factory=list, description="Target job titles. Empty: derived from your profile/resume"
    )
    locations: list[str] = Field(
        default_factory=list, description="Cities/countries and/or 'Remote'. Empty: from your profile"
    )
    remote_only: bool = False
    sponsorship_required: bool = Field(default=False, description="Drop jobs that explicitly refuse sponsorship")
    strict_location: bool = Field(default=True, description="Drop jobs outside the requested locations")
    max_results: int = Field(default=60, ge=1, le=200)
    use_llm_expansion: bool = True

    @field_validator("roles", "locations")
    @classmethod
    def _clean(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


class RawJobPosting(BaseModel):
    """A posting as returned by one source, before normalisation."""

    title: str
    url: str
    snippet: str = ""
    company: str | None = None
    location: str | None = None
    remote: bool | None = None
    workplace: str | None = None  # REMOTE | HYBRID | ONSITE when the source states it explicitly
    tags: list[str] = Field(default_factory=list)
    source: str
    engine: str | None = None
    posted_at: datetime | None = None
    verified: bool = False  # details confirmed via the ATS's own API


class SearchResponse(BaseModel):
    roles: list[str] = Field(default_factory=list, description="Roles actually searched (may be auto-derived)")
    locations: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list, description="Roles plus related titles matched against")
    queries: list[str]
    total_raw: int
    total_results: int
    filtered_out: dict[str, int] = Field(default_factory=dict, description="Reason -> number of jobs removed")
    results: list[JobWithMatch]
    errors: list[str] = Field(default_factory=list)
