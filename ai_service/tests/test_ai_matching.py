"""AI matching: resume similarity, AI review of the top matches, learning from what you hide and apply to."""

from datetime import UTC, datetime

import numpy as np

from ai_service.app.database.session import AsyncSessionLocal
from ai_service.app.models.application import ApplicationModel
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.schemas.match import JobWithMatch, MatchResult
from ai_service.app.services.matching.feedback import FeedbackModel
from ai_service.app.services.matching.matching_engine import MatchingEngineService
from ai_service.app.services.matching.reviewer import JobReviewer, carry_over, profile_fingerprint
from ai_service.app.services.matching.semantic import SemanticMatcher, calibrate
from ai_service.tests.fakes import RESUME

CANDIDATE = CandidateProfile(name="Asha", current_role="AI Engineer", years_of_experience=2, skills=["Python", "LLMs"])


def _job(job_id: str, title: str, description: str = "LLM agents and RAG pipelines in Python. " * 10) -> NormalizedJob:
    return NormalizedJob(
        id=job_id,
        title=title,
        company="Acme",
        description=description,
        required_skills=["Python", "LLMs"],
        application_url=f"https://job-boards.greenhouse.io/acme/jobs/{abs(hash(job_id)) % 10**8}",
    )


class FakeEmbedder:
    """Vectors from keywords: texts about LLMs point one way, others another."""

    def __init__(self) -> None:
        self.embedded = 0

    def embed(self, texts):
        for text in texts:
            self.embedded += 1
            yield np.array([1.0, 0.0]) if "LLM" in text else np.array([0.6, 0.8])


async def test_resume_similarity_scores_and_caches():
    matcher = SemanticMatcher()
    assert await matcher.scores(CANDIDATE, [_job("a", "AI Engineer")]) == {}  # model not loaded: no scores
    matcher._model = FakeEmbedder()
    jobs = [
        _job("a", "AI Engineer"),
        _job("b", "Accountant", "Ledgers and tax filings. " * 20),
        _job("c", "x", "short"),
    ]
    scores = await matcher.scores(CANDIDATE.model_copy(update={"summary": "Builds LLM apps"}), jobs)
    assert scores["a"] == 100.0 and scores["b"] == 0.0 and "c" not in scores  # too short to compare
    before = matcher._model.embedded
    await matcher.scores(CANDIDATE.model_copy(update={"summary": "Builds LLM apps"}), jobs)
    assert matcher._model.embedded == before  # vectors are cached
    assert calibrate(0.889) == 100.0 and calibrate(0.734) == 47.9 and calibrate(0.5) == 0.0


class VerdictLLM:
    available = True

    def __init__(self, verdicts: dict[str, tuple[str, str]]) -> None:
        self.verdicts, self.calls = verdicts, 0

    async def complete_json(self, system, user, **_):
        self.calls += 1
        reviews = []
        for line in user.splitlines():
            if line.startswith("[") and "]" in line:
                number, title = line[1 : line.index("]")], line[line.index("]") + 2 :].split(" at ")[0]
                verdict, reason = self.verdicts.get(title, ("possible", "Fits"))
                reviews.append({"id": number, "verdict": verdict, "reason": reason})
        return {"reviews": reviews}


def _scored(job: NormalizedJob, score: float) -> JobWithMatch:
    return JobWithMatch(job=job, match=MatchResult(job_id=job.id, overall_match=score))


async def test_ai_review_adjusts_scores_and_is_cached():
    llm = VerdictLLM({"Research Scientist": ("no", "PhD required"), "LLM Engineer": ("strong", "Same stack")})
    reviewer = JobReviewer(llm)
    reviewer.top_n = 20
    items = [_scored(_job("r", "Research Scientist"), 90), _scored(_job("l", "LLM Engineer"), 80)]
    reviewed = await reviewer.review(CANDIDATE, items)
    by_id = {r.job.id: r.match for r in reviewed}
    assert by_id["r"].ai_verdict == "no" and by_id["r"].overall_match == 40 and by_id["r"].ai_reason == "PhD required"
    assert by_id["l"].overall_match == 85 and reviewed[0].job.id == "l"  # re-sorted after the verdicts
    assert any("AI review: Not a fit" in r for r in by_id["r"].reasons)
    await reviewer.review(CANDIDATE, items)
    assert llm.calls == 1  # cached per job and profile

    # Re-scoring keeps the verdict while the profile is unchanged, and drops it after a change.
    fingerprint = profile_fingerprint(CANDIDATE)
    fresh = MatchResult(job_id="r", overall_match=90)
    assert carry_over(by_id["r"], fresh, fingerprint).overall_match == 40
    changed = profile_fingerprint(CANDIDATE.model_copy(update={"skills": ["Java"]}))
    assert carry_over(by_id["r"], fresh, changed).overall_match == 90


async def test_feedback_from_hidden_and_applied_jobs(client):
    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    candidate = (await client.get("/api/v1/candidates/me")).json()
    jobs = [
        _job("ann1", "AI Data Annotator"),
        _job("ann2", "Data Annotation Specialist"),
        _job("ai1", "AI Engineer"),
        _job("ai2", "LLM Engineer"),
    ]
    async with AsyncSessionLocal() as session:
        repo = JobRepository(session)
        await repo.upsert_many([JobWithMatch(job=j) for j in jobs])
        await repo.set_hidden("ann1", True)
        await repo.set_hidden("ann2", True)
        now = datetime.now(UTC)
        for job_id in ("ai1", "ai2"):
            session.add(
                ApplicationModel(
                    id=f"app-{job_id}", candidate_id=candidate["id"], job_id=job_id, job_title="t", company="Acme",
                    application_url="https://x", status="APPLIED", mode="manual", created_at=now, updated_at=now,
                )
            )  # fmt: skip
        await session.commit()
        feedback = await FeedbackModel.load(session)

    assert len(feedback.liked) == 2 and len(feedback.disliked) == 2
    points, why = feedback.adjust(_job("new-ann", "Image Annotation Specialist"))
    assert points < 0 and "hid" in why
    points, why = feedback.adjust(_job("new-ai", "Machine Learning Engineer"))
    assert points > 0 and "applied" in why
    assert feedback.adjust(_job("other", "Frontend Engineer"))[0] == 0.0

    engine = MatchingEngineService()
    profile = CandidateProfile.model_validate(candidate)
    plain = engine.evaluate_match(profile, _job("new-ai", "Machine Learning Engineer"))
    nudged = engine.evaluate_match(profile, _job("new-ai", "Machine Learning Engineer"), feedback=feedback)
    assert nudged.overall_match > plain.overall_match and any("applied" in r for r in nudged.reasons)


def test_feedback_needs_a_few_examples():
    model = FeedbackModel()
    assert not model.active and model.adjust(_job("x", "AI Engineer")) == (0.0, None)
