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
    experience: str = Field(default="ANY", description="Experience filter range e.g. 0-2, 1-3, 2-4, 3-5, 4-6, 5-8, 8+")
    posted_within: str = Field(default="any", description="Date posted filter: any, 24h, 7d, 30d")
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
    # Set by company-board sources: the ATS board ("greenhouse:acme") and job id, for jobs whose URL is the
    # company's own careers site, so their details can still be fetched from the ATS's API.
    board: str | None = None
    board_job_id: str | None = None
    # Structured pay when the source states it (otherwise parsed from the text)
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None


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


class SearchProgress(BaseModel):
    """One completed stage of a streamed search (POST /search/stream)."""

    stage: str
    label: str
    detail: str = ""
