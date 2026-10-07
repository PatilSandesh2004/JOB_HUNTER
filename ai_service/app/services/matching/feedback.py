"""Learn from what you do: jobs you hide push similar jobs down, jobs you apply to push similar jobs up.

Similarity is the role-title fit plus shared skills, so hiding a few "Data Annotator" jobs lowers other
annotation jobs without touching AI engineering roles. The effect is small (at most 8 points) and shown in
"Why this score", and it needs a few examples of each kind before it does anything.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.models.application import ApplicationModel
from ai_service.app.models.job import JobModel
from ai_service.app.schemas.application import ApplicationStatus
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.services.matching.roles import role_similarity

MAX_POINTS = 8.0
MIN_EXAMPLES = 2
MIN_SIMILARITY = 0.65
MAX_EXAMPLES = 200
_ENGAGED = [
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
    ApplicationStatus.PENDING_APPROVAL,
    ApplicationStatus.SUBMITTING,
    ApplicationStatus.PROCESSING,
]


@dataclass(frozen=True)
class Example:
    job_id: str
    title: str
    skills: frozenset[str]


@dataclass
class FeedbackModel:
    liked: list[Example] = field(default_factory=list)
    disliked: list[Example] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return len(self.liked) >= MIN_EXAMPLES or len(self.disliked) >= MIN_EXAMPLES

    @classmethod
    async def load(cls, session: AsyncSession) -> "FeedbackModel":
        hidden = await session.scalars(
            select(JobModel)
            .where(JobModel.hidden_at.is_not(None))
            .order_by(JobModel.hidden_at.desc())
            .limit(MAX_EXAMPLES)
        )
        rows = await session.execute(
            select(JobModel, ApplicationModel.status)
            .join(ApplicationModel, ApplicationModel.job_id == JobModel.id)
            .order_by(ApplicationModel.updated_at.desc())
            .limit(MAX_EXAMPLES * 2)
        )
        liked, disliked = [], [_example(j) for j in hidden]
        for job, status in rows:
            if status in {s.value for s in _ENGAGED}:
                liked.append(_example(job))
            elif status == ApplicationStatus.DISMISSED.value:
                disliked.append(_example(job))
        return cls(liked=liked[:MAX_EXAMPLES], disliked=disliked[:MAX_EXAMPLES])

    def adjust(self, job: NormalizedJob) -> tuple[float, str | None]:
        """(points to add, explanation) for a job, from its similarity to jobs you liked or rejected."""
        if not self.active:
            return 0.0, None
        skills = frozenset([*job.required_skills, *job.preferred_skills])
        best_like = self._closest(job, skills, self.liked) if len(self.liked) >= MIN_EXAMPLES else None
        best_dislike = self._closest(job, skills, self.disliked) if len(self.disliked) >= MIN_EXAMPLES else None
        like = best_like[0] if best_like else 0.0
        dislike = best_dislike[0] if best_dislike else 0.0
        if like == dislike == 0.0:
            return 0.0, None
        points = round(MAX_POINTS * max(-1.0, min(1.0, like - dislike)), 1)
        if points > 0 and best_like:
            return points, f"Similar to '{best_like[1]}', which you applied to (+{points:g})"
        if points < 0 and best_dislike:
            return points, f"Similar to '{best_dislike[1]}', which you hid or dismissed ({points:g})"
        return 0.0, None

    @staticmethod
    def _closest(job: NormalizedJob, skills: frozenset[str], examples: list[Example]) -> tuple[float, str] | None:
        best: tuple[float, str] | None = None
        for example in examples:
            if example.job_id == job.id:
                continue
            title = role_similarity(example.title, job.title) / 100
            overlap = len(skills & example.skills) / len(skills | example.skills) if skills and example.skills else 0.0
            score = 0.75 * title + 0.25 * overlap
            if score >= MIN_SIMILARITY and (best is None or score > best[0]):
                best = (score, example.title)
        if best is None:
            return None
        # Rescale MIN_SIMILARITY..1 to 0..1 so a borderline resemblance has little effect.
        return (best[0] - MIN_SIMILARITY) / (1 - MIN_SIMILARITY), best[1]


def _example(job: JobModel) -> Example:
    return Example(job.id, job.title, frozenset([*(job.required_skills or []), *(job.preferred_skills or [])]))
