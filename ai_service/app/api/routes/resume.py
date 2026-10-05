import os
import shutil
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from ai_service.app.database.session import get_db
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.services.resume.resume_parser import ResumeParserService
from ai_service.app.services.resume.resume_service import ResumeService
from ai_service.app.repositories.candidate_repository import CandidateRepository

router = APIRouter(prefix="/resume", tags=["resume"])


@router.post("/upload", response_model=CandidateProfile)
async def upload_resume(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not (file.filename.endswith(".pdf") or file.filename.endswith(".docx")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF and DOCX files are supported.",
        )
        
    os.makedirs("/tmp/jobpilot_resumes", exist_ok=True)
    file_path = f"/tmp/jobpilot_resumes/{file.filename}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    parser = ResumeParserService()
    repo = CandidateRepository(db)
    service = ResumeService(parser=parser, repo=repo)
    
    profile = await service.process_resume_file(file_path)
    return profile
