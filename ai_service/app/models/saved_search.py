from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ai_service.app.database.session import Base
from ai_service.app.models._mixins import TimestampMixin


class SavedSearchModel(TimestampMixin, Base):
    """A search you saved; it runs on its own every `interval_hours` and alerts you to strong new matches."""

    __tablename__ = "saved_searches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    request: Mapped[dict[str, Any]] = mapped_column(JSON)  # a SearchQueryRequest
    interval_hours: Mapped[float] = mapped_column(Float, default=24.0)  # 0: only when you press Run
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_found: Mapped[int] = mapped_column(Integer, default=0)
    last_new: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
