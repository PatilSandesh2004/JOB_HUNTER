from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ai_service.app.database.session import Base
from ai_service.app.models._mixins import TimestampMixin


class ScreeningAnswerModel(TimestampMixin, Base):
    """A reusable answer to an application-form question, written or approved by the user."""

    __tablename__ = "screening_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question: Mapped[str] = mapped_column(String(500))  # as the form worded it
    question_key: Mapped[str] = mapped_column(String(300), unique=True, index=True)  # normalised, for lookup
    answer: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="user")  # "user" | "suggested" (accepted AI draft)
