import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.models.screening_answer import ScreeningAnswerModel
from ai_service.app.schemas.screening import ScreeningAnswerWrite
from ai_service.app.services.screening.answer_bank import normalize_question


class ScreeningAnswerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[ScreeningAnswerModel]:
        stmt = select(ScreeningAnswerModel).order_by(ScreeningAnswerModel.updated_at.desc())
        return list((await self.session.scalars(stmt)).all())

    async def as_lookup(self) -> dict[str, str]:
        """normalised question -> answer, for AnswerBook."""
        return {row.question_key: row.answer for row in await self.list_all()}

    async def upsert_many(self, items: list[ScreeningAnswerWrite]) -> None:
        """Save answers keyed by normalised question; an empty answer deletes the saved one."""
        by_key = {normalize_question(i.question): i for i in items if normalize_question(i.question)}
        if not by_key:
            return
        stmt = select(ScreeningAnswerModel).where(ScreeningAnswerModel.question_key.in_(by_key))
        existing = {row.question_key: row for row in (await self.session.scalars(stmt)).all()}
        for key, item in by_key.items():
            row, answer = existing.get(key), item.answer.strip()
            if not answer:
                if row is not None:
                    await self.session.delete(row)
            elif row is None:
                self.session.add(
                    ScreeningAnswerModel(
                        id=str(uuid.uuid4()),
                        question=item.question.strip(),
                        question_key=key,
                        answer=answer,
                        source=item.source,
                    )
                )
            else:
                row.question, row.answer, row.source = item.question.strip(), answer, item.source
        await self.session.commit()

    async def delete(self, answer_id: str) -> bool:
        row = await self.session.get(ScreeningAnswerModel, answer_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True
