from sqlalchemy.ext.asyncio import AsyncSession
from ai_service.app.models.application import ApplicationModel
from ai_service.app.models.job import JobModel
from ai_service.app.models.candidate import CandidateModel
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.repositories.candidate_repository import CandidateRepository

class ApplicationInsightsService:
    def __init__(self, db: AsyncSession, llm: LLMClient):
        self.db = db
        self.llm = llm

    async def generate_insights(self, application_id: str, db: AsyncSession = None) -> dict:
        """Generates interview preparation insights for a specific application."""
        db = db or self.db
        app = await db.get(ApplicationModel, application_id)
        if not app:
            raise ValueError("Application not found")
            
        job = await db.get(JobModel, app.job_id)
        if not job:
            raise ValueError("Job not found")
            
        candidate = await CandidateRepository(db).get_active()
        if not candidate:
            raise ValueError("Candidate profile not found")

        system_prompt = "You are an expert technical recruiter and interview coach. Always respond in valid JSON matching the requested schema."
        
        user_prompt = f"""
        You are preparing a candidate for an interview for the following job:
        Title: {job.title}
        Company: {job.company}
        Description:
        {job.description}
        
        Here is the candidate's profile:
        Years of Experience: {candidate.years_of_experience}
        Summary: {candidate.summary or ''}
        Skills: {', '.join(candidate.skills)}
        
        Provide a structured JSON output with the following exact keys:
        - "missing_skills": A list of up to 3 strings describing skills required by the job that the candidate lacks.
        - "technical_topics": A list of up to 3 strings describing technical concepts the candidate should study.
        - "behavioral_questions": A list of up to 3 behavioral questions the candidate should prepare to answer based on the company or role.
        """
        
        insights = await self.llm.complete_json(system_prompt, user_prompt)
        return insights
