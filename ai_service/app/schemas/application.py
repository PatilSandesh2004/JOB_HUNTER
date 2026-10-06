from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApplicationStatus(StrEnum):
    PROCESSING = "PROCESSING"  # agent is preparing materials / filling the form
    PENDING_APPROVAL = "PENDING_APPROVAL"  # form filled (not submitted); waiting for the user
    SUBMITTING = "SUBMITTING"
    APPLIED = "APPLIED"  # submitted and a confirmation was detected
    NEEDS_MANUAL = "NEEDS_MANUAL"  # captcha, login wall, missing required fields, unverified submit
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"  # user opened the company site to apply themselves
    FAILED = "FAILED"
    DISMISSED = "DISMISSED"  # user declined
    INTERVIEW = "INTERVIEW"
    REJECTED = "REJECTED"  # employer declined


class ApplyMode(StrEnum):
    REVIEW = "review"  # agent fills the form, you approve before it submits
    AUTO = "auto"  # agent submits when the form is complete and has no CAPTCHA
    MANUAL = "manual"  # you apply on the company site; JobPilot tracks it and drafts a cover letter


class ApplicationCreate(BaseModel):
    job_id: str
    mode: ApplyMode = ApplyMode.REVIEW
    cover_letter: str | None = Field(default=None, description="Use this text instead of generating one")


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
    created_at: datetime
    updated_at: datetime
