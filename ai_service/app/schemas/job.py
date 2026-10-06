from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field


class WorkplaceType(StrEnum):
    REMOTE = "REMOTE"
    HYBRID = "HYBRID"
    ONSITE = "ONSITE"
    UNKNOWN = "UNKNOWN"


class RemoteScope(StrEnum):
    WORLDWIDE = "WORLDWIDE"
    US_ONLY = "US_ONLY"
    EU_ONLY = "EU_ONLY"
    UK_ONLY = "UK_ONLY"
    INDIA_ONLY = "INDIA_ONLY"
    ASIA = "ASIA"
    TIMEZONE_RESTRICTED = "TIMEZONE_RESTRICTED"
    NOT_REMOTE = "NOT_REMOTE"
    UNKNOWN = "UNKNOWN"


class VisaSponsorshipStatus(StrEnum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class VisaSponsorshipEvidence(BaseModel):
    """Sponsorship status backed by an explicit quote; never guessed."""

    status: VisaSponsorshipStatus = VisaSponsorshipStatus.UNKNOWN
    evidence: str | None = None
    source_url: str | None = None
    confidence: Confidence = Confidence.LOW


class NormalizedJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    company: str
    description: str = ""
    location: str = "Unknown"
    workplace_type: WorkplaceType = WorkplaceType.UNKNOWN
    remote_scope: RemoteScope = RemoteScope.UNKNOWN
    employment_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    experience_required: float | None = None
    required_skills: list[str] = Field(default_factory=list)
    visa_sponsorship: VisaSponsorshipEvidence = Field(default_factory=VisaSponsorshipEvidence)
    relocation: bool = False
    application_url: str
    ats: str = "other"
    source: str = "searxng"
    verified: bool = False  # details confirmed through the ATS's API
    posted_at: datetime | None = None
    closed_at: datetime | None = None  # the job board reported the posting gone
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @computed_field
    @property
    def auto_apply_supported(self) -> bool:
        """The browser agent can fill this site's form; otherwise only manual apply is offered."""
        from ai_service.app.services.jobs.ats import detect_ats

        return detect_ats(self.application_url).auto_apply_supported
