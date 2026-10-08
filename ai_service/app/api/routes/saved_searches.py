from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.api.deps import get_saved_search_service
from ai_service.app.database.session import get_db
from ai_service.app.models.saved_search import SavedSearchModel
from ai_service.app.schemas.search import SearchQueryRequest
from ai_service.app.services.search.saved_search_service import SavedSearchService, as_dict

router = APIRouter(prefix="/saved-searches", tags=["saved searches"])


class SavedSearchCreate(BaseModel):
    name: str = Field(default="", max_length=120)
    request: SearchQueryRequest
    interval_hours: float = Field(default=24, ge=0, le=168, description="0: only when you press Run")


class SavedSearchPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    interval_hours: float | None = Field(default=None, ge=0, le=168)
    enabled: bool | None = None


@router.get("")
async def list_saved_searches(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.scalars(select(SavedSearchModel).order_by(SavedSearchModel.created_at.desc()))).all()
    return [as_dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def save_search(
    payload: SavedSearchCreate,
    db: AsyncSession = Depends(get_db),
    service: SavedSearchService = Depends(get_saved_search_service),
) -> dict:
    """Save a search. It runs every `interval_hours` and alerts you to strong new matches."""
    return as_dict(await service.create(db, payload.name, payload.request, payload.interval_hours))


@router.patch("/{search_id}")
async def update_saved_search(search_id: str, patch: SavedSearchPatch, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(SavedSearchModel, search_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved search not found")
    for key, value in patch.model_dump(exclude_none=True).items():
        setattr(row, key, value.strip() if isinstance(value, str) else value)
    await db.commit()
    await db.refresh(row)
    return as_dict(row)


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_search(search_id: str, db: AsyncSession = Depends(get_db)) -> None:
    row = await db.get(SavedSearchModel, search_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved search not found")
    await db.delete(row)
    await db.commit()


@router.post("/{search_id}/run")
async def run_saved_search(search_id: str, service: SavedSearchService = Depends(get_saved_search_service)) -> dict:
    """Run a saved search now. Its jobs are stored; use GET /jobs to see them."""
    return as_dict(await service.run(search_id))
