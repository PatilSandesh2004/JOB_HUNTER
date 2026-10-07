import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.api.deps import get_resume_parser
from ai_service.app.core.config import settings
from ai_service.app.database.session import get_db
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.services.resume.resume_parser import SUPPORTED_EXTENSIONS, ResumeParserService

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.get("/me", response_model=CandidateProfile | None)
async def get_profile(db: AsyncSession = Depends(get_db)):
    return await CandidateRepository(db).get_active()


@router.put("/me", response_model=CandidateProfile)
async def save_profile(profile: CandidateProfile, db: AsyncSession = Depends(get_db)):
    return await CandidateRepository(db).save(profile)


@router.post("/me/resume", response_model=CandidateProfile)
async def upload_resume(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    parser: ResumeParserService = Depends(get_resume_parser),
):
    """Parse a resume and merge it into the active profile. Preferences you already set are kept."""
    extension = Path(file.filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}")
    data = await file.read(settings.max_resume_bytes + 1)
    if len(data) > settings.max_resume_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Resume is larger than 10 MB")

    parsed = await parser.parse(parser.extract_text(data, file.filename or f"resume{extension}"))

    # Stored under a generated name; the original filename never touches the filesystem path.
    stored = settings.resumes_dir / f"{uuid.uuid4()}{extension}"
    stored.write_bytes(data)

    repo = CandidateRepository(db)
    current = await repo.get_active()
    merged = _merge_into(current, parsed) if current else parsed
    return await repo.save(merged, resume_path=str(stored))


def _merge_into(current: CandidateProfile, parsed: CandidateProfile) -> CandidateProfile:
    """Parsed resume values replace profile facts; user-set preferences are preserved."""
    data = current.model_dump()
    for key, value in parsed.model_dump(exclude={"id", "preferences", "resume_filename"}).items():
        if value not in (None, "", [], 0, 0.0):
            data[key] = value
    return CandidateProfile.model_validate(data)

@router.post("/me/connections/upload")
async def upload_connections(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a LinkedIn Connections CSV file."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Must be a .csv file")
        
    candidate = await CandidateRepository(db).get_active()
    if not candidate:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Create a profile first")
        
    data = await file.read(1024 * 1024 * 5) # max 5MB
    from ai_service.app.repositories.connection_repository import ConnectionRepository
    repo = ConnectionRepository(db)
    try:
        count = await repo.import_csv(candidate.id, data)
        return {"message": f"Successfully imported {count} connections.", "count": count}
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Failed to parse CSV: {str(e)}")
