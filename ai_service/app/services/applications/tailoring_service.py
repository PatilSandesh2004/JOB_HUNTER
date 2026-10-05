from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.integrations.llm.llm_client import LLMClient


class ApplicationTailoringService:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    # Generate tailored cover letter aligning candidate experience with job requirements.
    async def generate_cover_letter(self, candidate: CandidateProfile, job: NormalizedJob) -> str:
        system_prompt = "You are an expert career agent writing compelling, professional cover letters."
        user_prompt = (
            f"Write a 3-paragraph cover letter for {candidate.name} applying for the {job.title} position at {job.company}.\n"
            f"Candidate skills: {', '.join(candidate.skills)}.\n"
            f"Job description: {job.description[:300]}..."
        )
        return await self.llm.generate_completion(system_prompt, user_prompt)

    # Generate tailored resume bullet points highlighting key matching skills.
    async def generate_tailored_resume(self, candidate: CandidateProfile, job: NormalizedJob) -> str:
        system_prompt = "You are a professional resume optimization expert."
        user_prompt = (
            f"Tailor candidate {candidate.name}'s resume for {job.title} at {job.company}.\n"
            f"Emphasize these target skills: {', '.join(job.required_skills)}."
        )
        return await self.llm.generate_completion(system_prompt, user_prompt)
