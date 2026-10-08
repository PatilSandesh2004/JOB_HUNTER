import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ai_service.app.database.session import Base


class ConnectionModel(Base):
    """One of your LinkedIn connections, imported from LinkedIn's Connections.csv export."""

    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    company: Mapped[str] = mapped_column(String(200), index=True)
    position: Mapped[str] = mapped_column(String(200))
    connected_on: Mapped[str | None] = mapped_column(String(50))
