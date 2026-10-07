import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.api.deps import get_application_service
from ai_service.app.core.config import settings
from ai_service.app.database.session import get_db
from ai_service.app.repositories.application_repository import ApplicationRepository, to_schema
from ai_service.app.schemas.application import ApplicationCreate, ApplicationRead, ApplicationStatus
from ai_service.app.services.applications.application_service import ApplicationService
from ai_service.app.api.deps import get_insights_service

router = APIRouter(prefix="/applications", tags=["applications"])


class ApplicationPatch(BaseModel):
    cover_letter: str | None = None
    status: ApplicationStatus | None = None


@router.get("", response_model=list[ApplicationRead])
async def list_applications(
    status_filter: list[ApplicationStatus] | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
):
    return [to_schema(row) for row in await ApplicationRepository(db).list_all(status_filter)]


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_202_ACCEPTED)
async def create_application(
    payload: ApplicationCreate,
    db: AsyncSession = Depends(get_db),
    service: ApplicationService = Depends(get_application_service),
):
    """Start an application. The agent work is queued and runs in the background.

    - `review`: draft a cover letter and pre-fill the form; you approve before it is submitted.
    - `auto`: same, but submit when the form is complete and has no CAPTCHA.
    - `manual`: you apply on the company site; it waits in "Did you apply?" and a letter is drafted for you.
    """
    return await service.create(db, payload)


@router.get("/{application_id}", response_model=ApplicationRead)
async def get_application(application_id: str, db: AsyncSession = Depends(get_db)):
    row = await ApplicationRepository(db).get(application_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return to_schema(row)


@router.patch("/{application_id}", response_model=ApplicationRead)
async def update_application(
    application_id: str,
    patch: ApplicationPatch,
    db: AsyncSession = Depends(get_db),
    service: ApplicationService = Depends(get_application_service),
):
    """Edit the cover letter, or record an outcome (APPLIED / INTERVIEW / REJECTED / DISMISSED)."""
    return await service.update(db, application_id, patch.cover_letter, patch.status)

@router.get("/{application_id}/insights")
async def get_application_insights(
    application_id: str,
    db: AsyncSession = Depends(get_db),
    service = Depends(get_insights_service)
):
    """Generate interview preparation insights."""
    try:
        return await service.generate_insights(application_id, db)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.post("/{application_id}/approve", response_model=ApplicationRead, status_code=status.HTTP_202_ACCEPTED)
async def approve_application(
    application_id: str,
    db: AsyncSession = Depends(get_db),
    service: ApplicationService = Depends(get_application_service),
):
    """Human approval: re-open the form, fill it and submit (queued)."""
    return await service.approve(db, application_id)


@router.post("/{application_id}/refill", response_model=ApplicationRead, status_code=status.HTTP_202_ACCEPTED)
async def refill_application(
    application_id: str,
    db: AsyncSession = Depends(get_db),
    service: ApplicationService = Depends(get_application_service),
):
    """Fill the form again (no submit), e.g. after saving answers to its open questions."""
    return await service.refill(db, application_id)


@router.get("/{application_id}/screenshot", response_class=FileResponse)
async def get_screenshot(application_id: str, db: AsyncSession = Depends(get_db)):
    """The most recent screenshot of the form."""
    row = await ApplicationRepository(db).get(application_id)
    path = Path(row.screenshot_path) if row and row.screenshot_path else None
    return FileResponse(_inside(path, settings.screenshots_dir, "No screenshot available"), media_type="image/png")


@router.get("/{application_id}/screenshots/{name}", response_class=FileResponse)
async def get_step_screenshot(application_id: str, name: str):
    """A screenshot referenced by the activity timeline."""
    if not re.fullmatch(rf"{re.escape(application_id)}-[\w-]+\.png", name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such screenshot")
    path = _inside(settings.screenshots_dir / name, settings.screenshots_dir, "No such screenshot")
    return FileResponse(path, media_type="image/png")


@router.get("/{application_id}/resume", response_class=FileResponse)
async def get_tailored_resume(application_id: str, db: AsyncSession = Depends(get_db)):
    """The tailored resume PDF attached to this application."""
    row = await ApplicationRepository(db).get(application_id)
    path = Path(row.tailored_resume_path) if row and row.tailored_resume_path else None
    path = _inside(path, settings.resumes_dir / "tailored", "No tailored resume for this application")
    return FileResponse(path, media_type="application/pdf", filename=f"resume-{row.company}.pdf".replace(" ", "-"))


def _inside(path: Path | None, directory: Path, missing: str) -> Path:
    """Serve only existing files directly inside `directory` (no traversal via stored paths)."""
    if path is None or not path.is_file() or path.resolve().parent != directory.resolve():
        raise HTTPException(status.HTTP_404_NOT_FOUND, missing)
    return path
