"""Your resumes: the main one (uploaded on the Profile tab) plus extra versions, e.g. "AI" and "Backend".

For each job, the version that covers most of the posting's skills is attached when applying.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.core.config import settings
from ai_service.app.models.candidate import CandidateModel
from ai_service.app.models.resume_variant import ResumeVariantModel
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.services.resume.resume_parser import ResumeParserService
from ai_service.app.services.skills.catalog import extract_skills, skill_pattern

logger = logging.getLogger("jobpilot.resumes")

MAX_VARIANTS = 8
MAIN_LABEL = "Main resume"


@dataclass(frozen=True)
class ResumeChoice:
    label: str
    path: str
    covered: int
    wanted: int
    variant_id: str | None = None  # None: the main resume


def coverage(text: str, job: NormalizedJob) -> tuple[float, int, int]:
    """(weighted share of the posting's skills the text mentions, required covered, required total)."""
    required, preferred = job.required_skills, job.preferred_skills
    if not text or not (required or preferred):
        return 0.0, 0, len(required)
    hits = [s for s in required if skill_pattern(s).search(text)]
    nice = [s for s in preferred if skill_pattern(s).search(text)]
    weight = len(required) + 0.5 * len(preferred)
    return (len(hits) + 0.5 * len(nice)) / weight, len(hits), len(required)


def _remove_stored(path: Path) -> None:
    """Delete a stored resume file, but only inside the resumes folder."""
    if path.parent.resolve() == settings.resumes_dir.resolve():
        path.unlink(missing_ok=True)


class ResumeLibrary:
    def __init__(self, parser: ResumeParserService) -> None:
        self.parser = parser
        self._texts: dict[tuple[str, float], str] = {}

    async def text_of(self, path: str | None) -> str:
        """Extracted text of a stored resume file (cached until the file changes); '' if unreadable."""
        if not path:
            return ""
        file = Path(path)
        try:
            stamp = (str(file), (await asyncio.to_thread(file.stat)).st_mtime)
        except OSError:
            return ""
        if stamp not in self._texts:
            try:
                data = await asyncio.to_thread(file.read_bytes)
                self._texts[stamp] = self.parser.extract_text(data, file.name)
            except Exception as exc:
                logger.info("Could not read resume %s: %s", file.name, exc)
                self._texts[stamp] = ""
        return self._texts[stamp]

    async def add(
        self, session: AsyncSession, candidate_id: str, label: str, filename: str, data: bytes
    ) -> ResumeVariantModel:
        existing = await self.list(session, candidate_id)
        if len(existing) >= MAX_VARIANTS:
            raise ValueError(f"You can keep up to {MAX_VARIANTS} resume versions; delete one first")
        text = self.parser.extract_text(data, filename)  # raises ResumeParseError for unreadable files
        extension = Path(filename).suffix.lower()
        stored = settings.resumes_dir / f"variant-{uuid.uuid4()}{extension}"
        await asyncio.to_thread(stored.write_bytes, data)
        row = ResumeVariantModel(
            id=str(uuid.uuid4()),
            candidate_id=candidate_id,
            label=label.strip()[:80] or Path(filename).stem[:80],
            filename=Path(filename).name[:255],
            path=str(stored),
            text=text[:60_000],
            skills=extract_skills(text),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    @staticmethod
    async def list(session: AsyncSession, candidate_id: str) -> list[ResumeVariantModel]:
        stmt = select(ResumeVariantModel).where(ResumeVariantModel.candidate_id == candidate_id)
        return list((await session.scalars(stmt.order_by(ResumeVariantModel.created_at))).all())

    @staticmethod
    async def delete(session: AsyncSession, variant_id: str) -> bool:
        row = await session.get(ResumeVariantModel, variant_id)
        if row is None:
            return False
        path = Path(row.path)
        await session.delete(row)
        await session.commit()
        await asyncio.to_thread(_remove_stored, path)
        return True

    async def best_for(
        self, session: AsyncSession, candidate: CandidateModel, job: NormalizedJob
    ) -> ResumeChoice | None:
        """The resume version that covers most of this job's skills (the main resume wins ties)."""
        variants = await self.list(session, candidate.id)
        if not variants:
            return None
        options = [(MAIN_LABEL, candidate.resume_path, await self.text_of(candidate.resume_path), None)]
        options += [(v.label, v.path, v.text, v.id) for v in variants]
        best: ResumeChoice | None = None
        best_share = -1.0
        for label, path, text, variant_id in options:
            if not path:
                continue
            share, covered, wanted = coverage(text, job)
            if share > best_share:
                best, best_share = ResumeChoice(label, path, covered, wanted, variant_id), share
        return best
