import uuid
from sqlalchemy import Column, String
from ai_service.app.database.session import Base

class ConnectionModel(Base):
    __tablename__ = "connections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = Column(String(36), nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    company = Column(String(200), nullable=False, index=True)
    position = Column(String(200), nullable=False)
    connected_on = Column(String(50))
