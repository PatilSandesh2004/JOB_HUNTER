from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.api.deps import get_application_service
from ai_service.app.core.config import settings
from ai_service.app.database.session import get_db
from ai_service.app.repositories.application_repository import ApplicationRepository, to_schema
from ai_service.app.schemas.application import ApplicationCreate, ApplicationRead, ApplicationStatus, ApplyMode
from ai_service.app.services.applications.application_service import ApplicationService

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
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    service: ApplicationService = Depends(get_application_service),
):
    """Start an application.

    - `review`: draft a cover letter and pre-fill the form; you approve before it is submitted.
    - `auto`: same, but submit when the form is complete and has no CAPTCHA.
    - `manual`: you apply on the company site; it waits in "Did you apply?" and a letter is drafted for you.
    """
    application, task = await service.create(db, payload)
    if task == "agent":
        background.add_task(service.process, application.id, payload.mode == ApplyMode.AUTO)
    elif task == "letter":
        background.add_task(service.draft_cover_letter, application.id)
    return application


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


@router.post("/{application_id}/approve", response_model=ApplicationRead, status_code=status.HTTP_202_ACCEPTED)
async def approve_application(
    application_id: str,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    service: ApplicationService = Depends(get_application_service),
):
    """Human approval: re-open the form, fill it and submit."""
    application = await service.approve(db, application_id)
    background.add_task(service.process, application.id, True)
    return application


@router.get("/{application_id}/screenshot", response_class=FileResponse)
async def get_screenshot(application_id: str, db: AsyncSession = Depends(get_db)):
    row = await ApplicationRepository(db).get(application_id)
    path = Path(row.screenshot_path) if row and row.screenshot_path else None
    # Only ever serve files from the screenshots directory.
    if path is None or not path.is_file() or path.resolve().parent != settings.screenshots_dir.resolve():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No screenshot available")
    return FileResponse(path, media_type="image/png")
