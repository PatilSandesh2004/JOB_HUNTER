from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ai_service.app.database.session import Base
from ai_service.app.models._mixins import TimestampMixin


class ApplicationModel(TimestampMixin, Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    # Denormalised for display so the queue renders without joins.
    job_title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200))
    application_url: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="review")
    cover_letter: Mapped[str | None] = mapped_column(Text)
    cover_letter_source: Mapped[str | None] = mapped_column(String(16))  # "llm" | "template" | "user"
    filled_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    missing_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    screenshot_path: Mapped[str | None] = mapped_column(String(1000))
    confirmation: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
