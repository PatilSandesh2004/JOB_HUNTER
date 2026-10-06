import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.models.candidate import CandidateModel
from ai_service.app.schemas.candidate import CandidateProfile


class CandidateRepository:
    """Single-user deployment: the most recently updated candidate is the active profile."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_model(self) -> CandidateModel | None:
        stmt = select(CandidateModel).order_by(CandidateModel.updated_at.desc()).limit(1)
        return (await self.session.scalars(stmt)).first()

    async def get_active(self) -> CandidateProfile | None:
        row = await self.get_active_model()
        return to_schema(row) if row else None

    async def get_model(self, candidate_id: str) -> CandidateModel | None:
        return await self.session.get(CandidateModel, candidate_id)

    async def save(self, profile: CandidateProfile, resume_path: str | None = None) -> CandidateProfile:
        row = await self.get_model(profile.id) if profile.id else await self.get_active_model()
        values = profile.model_dump(mode="json", exclude={"id", "resume_filename"})
        if row is None:
            row = CandidateModel(id=str(uuid.uuid4()), **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        if resume_path:
            row.resume_path = resume_path
        await self.session.commit()
        await self.session.refresh(row)
        return to_schema(row)


def to_schema(row: CandidateModel) -> CandidateProfile:
    profile = CandidateProfile.model_validate(row)
    profile.resume_filename = Path(row.resume_path).name if row.resume_path else None
    return profile
