from enum import Enum
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


# Granular enum defining precise remote work scopes.
class RemoteScope(str, Enum):
    REMOTE_WORLDWIDE = "REMOTE_WORLDWIDE"
    REMOTE_US_ONLY = "REMOTE_US_ONLY"
    REMOTE_EU_ONLY = "REMOTE_EU_ONLY"
    REMOTE_UK_ONLY = "REMOTE_UK_ONLY"
    REMOTE_INDIA_ONLY = "REMOTE_INDIA_ONLY"
    REMOTE_ASIA = "REMOTE_ASIA"
    REMOTE_TIMEZONE_RESTRICTED = "REMOTE_TIMEZONE_RESTRICTED"
    HYBRID = "HYBRID"
    ONSITE = "ONSITE"
    UNKNOWN = "UNKNOWN"


# Visa sponsorship status enum with strict non-guessing requirements.
class VisaSponsorshipStatus(str, Enum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


# Structure tracking explicit evidence for visa sponsorship status.
class VisaSponsorshipEvidence(BaseModel):
    status: VisaSponsorshipStatus = VisaSponsorshipStatus.UNKNOWN
    evidence: Optional[str] = None
    source_url: Optional[str] = None
    confidence: str = "LOW"  # HIGH, MEDIUM, LOW


# Comprehensive Pydantic model for normalized job listings across all sources.
class NormalizedJob(BaseModel):
    id: Optional[str] = None
    title: str
    company: str
    company_id: Optional[str] = None
    description: str = ""
    location: str = "Unknown"
    country: str = "Unknown"
    city: Optional[str] = None
    company_location: Optional[str] = None
    job_location: Optional[str] = None
    workplace_type: RemoteScope = RemoteScope.UNKNOWN
    remote_scope: RemoteScope = RemoteScope.UNKNOWN
    employment_type: str = "Full-time"
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = "USD"
    experience_required: Optional[int] = None
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)
    qualifications: List[str] = Field(default_factory=list)
    visa_sponsorship: VisaSponsorshipEvidence = Field(default_factory=VisaSponsorshipEvidence)
    relocation: bool = False
    application_url: str
    source: str = "searxng"
    source_job_id: Optional[str] = None
    posted_at: Optional[datetime] = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
