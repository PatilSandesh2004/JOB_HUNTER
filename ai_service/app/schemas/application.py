from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApplicationStatus(StrEnum):
    SAVED = "SAVED"  # bookmarked to apply later
    PROCESSING = "PROCESSING"  # agent is preparing materials / filling the form
    PENDING_APPROVAL = "PENDING_APPROVAL"  # form filled (not submitted); waiting for the user
    SUBMITTING = "SUBMITTING"
    APPLIED = "APPLIED"  # submitted and a confirmation was detected
    NEEDS_MANUAL = "NEEDS_MANUAL"  # captcha, login wall, missing required fields, unverified submit
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"  # user opened the company site to apply themselves
    FAILED = "FAILED"
    DISMISSED = "DISMISSED"  # user declined
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"  # employer declined


class ApplyMode(StrEnum):
    REVIEW = "review"  # agent fills the form, you approve before it submits
    AUTO = "auto"  # agent submits when the form is complete and has no CAPTCHA
    MANUAL = "manual"  # you apply on the company site; JobPilot tracks it and drafts a cover letter
    SAVE = "save"  # bookmark the job to apply later; nothing is filled or drafted yet


class ApplicationCreate(BaseModel):
    job_id: str
    mode: ApplyMode = ApplyMode.REVIEW
    cover_letter: str | None = Field(default=None, description="Use this text instead of generating one")
    tailor_resume: bool | None = Field(
        default=None, description="Attach a resume tailored to this job. Default: your profile preference"
    )


class ApplicationEvent(BaseModel):
    """One step in the agent's activity timeline."""

    at: datetime
    step: str
    detail: str = ""
    screenshot: str | None = Field(default=None, description="Fetch via GET /applications/{id}/screenshots/{name}")


class ScreeningQuestion(BaseModel):
    """A required form question the agent could not answer from your profile or answer bank."""

    label: str
    kind: str  # text | textarea | select | radio | number | email | url | tel
    options: list[str] = Field(default_factory=list)
    required: bool = True
    suggestion: str | None = Field(default=None, description="AI-drafted from your profile; check before saving")


class ResumeReport(BaseModel):
    """How your profile lines up with the posting's keywords."""

    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list, description="The posting asks for these; not in profile")
    emphasised_bullets: int = 0
    keyword_coverage: float = 0.0  # percent of posting skills found in your profile


class ApplicationUpdate(BaseModel):
    cover_letter: str | None = None


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    candidate_id: str
    job_id: str
    job_title: str
    company: str
    application_url: str
    status: ApplicationStatus
    mode: ApplyMode
    cover_letter: str | None = None
    cover_letter_source: str | None = None
    filled_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    has_screenshot: bool = False
    confirmation: str | None = None
    error: str | None = None
    applied_at: datetime | None = None
    events: list[ApplicationEvent] = Field(default_factory=list)
    questions: list[ScreeningQuestion] = Field(default_factory=list)
    has_tailored_resume: bool = False
    resume_report: ResumeReport | None = None
    follow_up_due: bool = Field(default=False, description="Applied a while ago with no news: time to follow up")
    created_at: datetime
    updated_at: datetime
