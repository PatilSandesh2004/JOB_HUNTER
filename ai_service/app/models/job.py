from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ai_service.app.database.session import Base
from ai_service.app.models._mixins import TimestampMixin


class JobModel(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    company: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(200), default="Unknown")
    workplace_type: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    remote_scope: Mapped[str] = mapped_column(String(48), default="UNKNOWN")
    employment_type: Mapped[str | None] = mapped_column(String(64))
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_currency: Mapped[str | None] = mapped_column(String(8))
    experience_required: Mapped[float | None] = mapped_column(Float)
    required_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    visa_sponsorship: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    relocation: Mapped[bool] = mapped_column(Boolean, default=False)
    application_url: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    ats: Mapped[str] = mapped_column(String(32), default="other")
    source: Mapped[str] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Latest match evaluation against the active candidate (single-user deployment).
    match: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # match["overall_match"] as a column, so listing can sort and page in SQL.
    overall_match: Mapped[float | None] = mapped_column(Float, index=True)
    # Set when the job board reports the posting gone; cleared if a search finds it open again.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
