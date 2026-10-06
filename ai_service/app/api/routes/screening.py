from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.database.session import get_db
from ai_service.app.repositories.screening_answer_repository import ScreeningAnswerRepository
from ai_service.app.schemas.screening import ScreeningAnswerRead, ScreeningAnswerWrite

router = APIRouter(prefix="/screening-answers", tags=["screening answers"])


@router.get("", response_model=list[ScreeningAnswerRead])
async def list_answers(db: AsyncSession = Depends(get_db)):
    """Your answer bank: reusable answers to application-form questions, newest first."""
    return await ScreeningAnswerRepository(db).list_all()


@router.put("", response_model=list[ScreeningAnswerRead])
async def save_answers(answers: list[ScreeningAnswerWrite], db: AsyncSession = Depends(get_db)):
    """Add or update answers, matched on the question's wording. An empty answer removes it."""
    repo = ScreeningAnswerRepository(db)
    await repo.upsert_many(answers)
    return await repo.list_all()


@router.delete("/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_answer(answer_id: str, db: AsyncSession = Depends(get_db)) -> None:
    if not await ScreeningAnswerRepository(db).delete(answer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Answer not found")
