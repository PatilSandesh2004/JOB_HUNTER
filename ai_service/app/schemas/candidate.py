from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RemotePreference(StrEnum):
    REMOTE_ONLY = "REMOTE_ONLY"
    HYBRID = "HYBRID"
    ONSITE = "ONSITE"
    ANY = "ANY"


class WorkExperience(BaseModel):
    company: str
    title: str
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None


class EducationItem(BaseModel):
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    graduation_year: int | None = None


class CandidatePreferences(BaseModel):
    preferred_roles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    remote_preference: RemotePreference = RemotePreference.ANY
    willing_to_relocate: bool = False
    visa_sponsorship_required: bool = False
    expected_salary: str | None = None
    notice_period: str | None = None
    blocked_companies: list[str] = Field(default_factory=list)  # never show jobs from these
    tailor_resume: bool = False  # attach a per-job tailored PDF instead of the uploaded resume
    auto_apply_high_matches: bool = False  # Full Auto-Pilot: automatically apply to >85% matches


class CandidateProfile(BaseModel):
    """Candidate data used for matching and form filling. Unknown fields stay empty, never invented."""

    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    name: str = ""
    email: EmailStr | None = None
    phone: str | None = None
    location: str | None = None
    current_role: str | None = None
    current_company: str | None = None
    years_of_experience: float = Field(default=0.0, ge=0, le=60)
    summary: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    skills: list[str] = Field(default_factory=list)
    work_experience: list[WorkExperience] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    preferences: CandidatePreferences = Field(default_factory=CandidatePreferences)
    resume_filename: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email_to_none(cls, value: object) -> object:
        return value or None

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name.split() else ""

    @property
    def last_name(self) -> str:
        parts = self.name.split()
        return " ".join(parts[1:]) if len(parts) > 1 else ""
