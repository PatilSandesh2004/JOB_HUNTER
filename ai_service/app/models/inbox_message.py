from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ai_service.app.database.session import Base
from ai_service.app.models._mixins import TimestampMixin


class InboxMessageModel(TimestampMixin, Base):
    """An email the inbox reader has already looked at, so it is processed once.

    Unrelated emails are stored only as a hash of their Message-ID (no sender, no subject).
    """

    __tablename__ = "inbox_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the Message-ID
    kind: Mapped[str] = mapped_column(String(16))  # job_alert | status_update | ignored
    sender: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
