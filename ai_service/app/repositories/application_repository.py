from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from ai_service.app.models.application import ApplicationModel


class ApplicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, app_data: dict) -> ApplicationModel:
        db_app = ApplicationModel(**app_data)
        self.session.add(db_app)
        await self.session.commit()
        await self.session.refresh(db_app)
        return db_app

    async def update_status(self, app_id: str, status: str, confirmation: Optional[str] = None) -> Optional[ApplicationModel]:
        stmt = select(ApplicationModel).where(ApplicationModel.id == app_id)
        result = await self.session.execute(stmt)
        app = result.scalars().first()
        if app:
            app.status = status
            if confirmation:
                app.confirmation = confirmation
            await self.session.commit()
            await self.session.refresh(app)
        return app

    async def list_by_candidate(self, candidate_id: str) -> List[ApplicationModel]:
        stmt = select(ApplicationModel).where(ApplicationModel.candidate_id == candidate_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
