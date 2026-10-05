from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from ai_service.app.models.candidate import CandidateModel


class CandidateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, candidate_data: dict) -> CandidateModel:
        stmt = select(CandidateModel).where(CandidateModel.email == candidate_data["email"])
        result = await self.session.execute(stmt)
        existing = result.scalars().first()

        if existing:
            for k, v in candidate_data.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        db_candidate = CandidateModel(**candidate_data)
        self.session.add(db_candidate)
        await self.session.commit()
        await self.session.refresh(db_candidate)
        return db_candidate

    async def get_by_id(self, candidate_id: str) -> Optional[CandidateModel]:
        stmt = select(CandidateModel).where(CandidateModel.id == candidate_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()
