import os
from typing import Optional
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.services.resume.resume_parser import ResumeParserService
from ai_service.app.repositories.candidate_repository import CandidateRepository


class ResumeService:
    def __init__(self, parser: ResumeParserService, repo: Optional[CandidateRepository] = None) -> None:
        self.parser = parser
        self.repo = repo

    # Service method processing raw uploaded resume file and extracting structured candidate profile.
    async def process_resume_file(self, file_path: str) -> CandidateProfile:
        text = self.parser.extract_text(file_path)
        profile = self.parser.parse(text)
        
        if self.repo:
            candidate_dict = {
                "id": profile.id,
                "name": profile.name,
                "email": profile.email,
                "phone": profile.phone,
                "location": profile.location,
                "current_role": profile.current_role,
                "years_of_experience": str(profile.years_of_experience),
                "skills": profile.skills,
                "work_experience": [w.model_dump() for w in profile.work_experience],
                "education": [e.model_dump() for e in profile.education],
                "projects": profile.projects,
                "certifications": profile.certifications,
                "preferences": profile.preferences.model_dump(),
                "raw_resume_path": file_path,
            }
            await self.repo.save(candidate_dict)
            
        return profile
