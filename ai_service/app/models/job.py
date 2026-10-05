from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Float, Boolean, JSON
from ai_service.app.database.session import Base


# SQLAlchemy ORM Model for storing normalized jobs in PostgreSQL.
class JobModel(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    company = Column(String, nullable=False, index=True)
    company_id = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    location = Column(String, nullable=True)
    country = Column(String, nullable=True)
    city = Column(String, nullable=True)
    workplace_type = Column(String, nullable=True)
    remote_scope = Column(String, nullable=True)
    employment_type = Column(String, nullable=True)
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    salary_currency = Column(String, nullable=True)
    experience_required = Column(Float, nullable=True)
    required_skills = Column(JSON, nullable=True)
    preferred_skills = Column(JSON, nullable=True)
    visa_sponsorship = Column(JSON, nullable=True)
    relocation = Column(Boolean, default=False)
    application_url = Column(String, unique=True, index=True, nullable=False)
    source = Column(String, nullable=False)
    source_job_id = Column(String, nullable=True)
    posted_at = Column(DateTime, nullable=True)
    scraped_at = Column(DateTime, default=datetime.utcnow)
