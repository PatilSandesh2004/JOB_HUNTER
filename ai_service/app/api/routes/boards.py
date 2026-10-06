from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ai_service.app.api.deps import get_board_source
from ai_service.app.services.search.board_source import BoardError, BoardSearchSource

router = APIRouter(prefix="/boards", tags=["company boards"])


class BoardRead(BaseModel):
    ats: str
    slug: str
    company: str
    source: str = Field(description="seed (built in), discovered (seen in search results) or watched (added by you)")


class BoardAdd(BaseModel):
    url: str = Field(min_length=3, max_length=500, description="Any job or careers link, or 'ats:company'")


class BoardAdded(BoardRead):
    open_jobs: int


@router.get("", response_model=list[BoardRead])
async def list_boards(boards: BoardSearchSource = Depends(get_board_source)):
    """Company job boards searched on every search, read through their public job APIs."""
    return [BoardRead(ats=b.ats, slug=b.slug, company=b.company, source=b.source) for b in boards.list_boards()]


@router.post("", response_model=BoardAdded, status_code=status.HTTP_201_CREATED)
async def watch_board(payload: BoardAdd, boards: BoardSearchSource = Depends(get_board_source)):
    """Watch a company: its whole job board is searched from now on."""
    try:
        board, open_jobs = await boards.watch(payload.url)
    except BoardError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return BoardAdded(ats=board.ats, slug=board.slug, company=board.company, source=board.source, open_jobs=open_jobs)


@router.delete("/{ats}/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_board(ats: str, slug: str, boards: BoardSearchSource = Depends(get_board_source)) -> None:
    if not boards.forget(ats, slug):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a watched or discovered board (built-in boards stay)")
