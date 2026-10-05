from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, ForeignKey
from ai_service.app.database.session import Base


# SQLAlchemy ORM Model for Application Tracking.
class ApplicationModel(Base):
    __tablename__ = "applications"

    id = Column(String, primary_key=True, index=True)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    status = Column(String, nullable=False, default="DISCOVERED")  # DISCOVERED, MATCHED, READY_TO_APPLY, PENDING_APPROVAL, APPLIED, REJECTED, OFFER
    resume_version = Column(Text, nullable=True)
    cover_letter = Column(Text, nullable=True)
    answers = Column(JSON, nullable=True)
    confirmation = Column(Text, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
