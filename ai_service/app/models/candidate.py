from typing import Any

from sqlalchemy import JSON, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ai_service.app.database.session import Base
from ai_service.app.models._mixins import TimestampMixin


class CandidateModel(TimestampMixin, Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(200))
    current_role: Mapped[str | None] = mapped_column(String(200))
    current_company: Mapped[str | None] = mapped_column(String(200))
    years_of_experience: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    github_url: Mapped[str | None] = mapped_column(String(500))
    portfolio_url: Mapped[str | None] = mapped_column(String(500))
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    work_experience: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    education: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resume_path: Mapped[str | None] = mapped_column(String(1000))
