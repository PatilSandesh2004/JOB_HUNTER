import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.api.deps import get_resume_library, get_resume_parser
from ai_service.app.core.config import settings
from ai_service.app.database.session import get_db
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.connection_repository import ConnectionCsvError, ConnectionRepository
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.services.resume.library import MAIN_LABEL, ResumeLibrary
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
    """Parsed resume values replace profile facts; user-set preferences are preserved. Target roles suggested
    from the resume are filled in only when you have not set any."""
    data = current.model_dump()
    for key, value in parsed.model_dump(exclude={"id", "preferences", "resume_filename"}).items():
        if value not in (None, "", [], 0, 0.0):
            data[key] = value
    if not current.preferences.preferred_roles and parsed.preferences.preferred_roles:
        data["preferences"]["preferred_roles"] = parsed.preferences.preferred_roles
    return CandidateProfile.model_validate(data)


@router.get("/me/resumes")
async def list_resumes(db: AsyncSession = Depends(get_db), library: ResumeLibrary = Depends(get_resume_library)):
    """Your main resume and extra versions. The version covering most of a job's skills is attached when applying."""
    model = await CandidateRepository(db).get_active_model()
    if model is None:
        return []
    main = []
    if model.resume_path:
        main = [{"id": None, "label": MAIN_LABEL, "filename": Path(model.resume_path).name, "skills": None}]
    variants = await library.list(db, model.id)
    return main + [{"id": v.id, "label": v.label, "filename": v.filename, "skills": v.skills} for v in variants]


@router.post("/me/resumes", status_code=status.HTTP_201_CREATED)
async def add_resume_version(
    file: UploadFile = File(...),
    label: str = Form(""),
    db: AsyncSession = Depends(get_db),
    library: ResumeLibrary = Depends(get_resume_library),
):
    """Add a resume version (e.g. "AI" or "Backend"). Your profile is not changed."""
    extension = Path(file.filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}")
    model = await CandidateRepository(db).get_active_model()
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload your main resume first (it creates your profile)")
    data = await file.read(settings.max_resume_bytes + 1)
    if len(data) > settings.max_resume_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Resume is larger than 10 MB")
    try:
        row = await library.add(db, model.id, label, file.filename or f"resume{extension}", data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"id": row.id, "label": row.label, "filename": row.filename, "skills": row.skills}


@router.delete("/me/resumes/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume_version(
    variant_id: str, db: AsyncSession = Depends(get_db), library: ResumeLibrary = Depends(get_resume_library)
) -> None:
    if not await library.delete(db, variant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume version not found")


MAX_CONNECTIONS_CSV_BYTES = 5 * 1024 * 1024


@router.post("/me/connections/upload")
async def upload_connections(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> dict:
    """Import LinkedIn's Connections.csv (Settings → Data privacy → Get a copy of your data).

    Replaces connections imported earlier."""
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload LinkedIn's Connections.csv file")
    candidate = await CandidateRepository(db).get_active()
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Create your profile first (upload your resume)")
    data = await file.read(MAX_CONNECTIONS_CSV_BYTES + 1)
    if len(data) > MAX_CONNECTIONS_CSV_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The CSV is larger than 5 MB")
    try:
        count = await ConnectionRepository(db).import_csv(candidate.id, data)
    except ConnectionCsvError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"message": f"Imported {count} connections.", "count": count}


@router.get("/me/connections")
async def connections_summary(db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    candidate = await CandidateRepository(db).get_active()
    return {"count": await ConnectionRepository(db).count(candidate.id) if candidate else 0}
