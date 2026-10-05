from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, Boolean
from ai_service.app.database.session import Base


# SQLAlchemy ORM Model for Candidate Profiles.
class CandidateModel(Base):
    __tablename__ = "candidates"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String, nullable=True)
    location = Column(String, nullable=True)
    current_role = Column(String, nullable=True)
    years_of_experience = Column(String, nullable=True)
    skills = Column(JSON, nullable=True)
    work_experience = Column(JSON, nullable=True)
    education = Column(JSON, nullable=True)
    projects = Column(JSON, nullable=True)
    certifications = Column(JSON, nullable=True)
    preferences = Column(JSON, nullable=True)
    raw_resume_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
