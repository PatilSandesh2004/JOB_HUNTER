from typing import List, Optional
from pydantic import BaseModel, Field
from ai_service.app.schemas.job import NormalizedJob, VisaSponsorshipStatus
from ai_service.app.schemas.candidate import CandidateProfile


class MatchResult(BaseModel):
    job_id: str
    job_title: str
    company: str
    overall_match: float = Field(..., description="Overall score between 0 and 100")
    skill_match: float = 0.0
    experience_match: float = 0.0
    location_match: float = 0.0
    sponsorship_match: float = 0.0
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    passed_hard_filters: bool = True
    explanation: str = ""


class MatchingEngineService:

    # Multi-stage evaluation method scoring job relevance against candidate profile.
    def evaluate_match(self, candidate: CandidateProfile, job: NormalizedJob) -> MatchResult:
        # Stage 1: Hard filters check
        passed = True
        sponsorship_score = 100.0

        if candidate.preferences.visa_sponsorship_required:
            if job.visa_sponsorship.status == VisaSponsorshipStatus.NO:
                passed = False
                sponsorship_score = 0.0
            elif job.visa_sponsorship.status == VisaSponsorshipStatus.UNKNOWN:
                sponsorship_score = 50.0

        # Stage 2: Skill matching
        candidate_skills_lower = {s.lower() for s in candidate.skills}
        matched = []
        missing = []
        
        target_skills = job.required_skills if job.required_skills else ["python", "software"]
        for sk in target_skills:
            if sk.lower() in candidate_skills_lower:
                matched.append(sk)
            else:
                missing.append(sk)

        total_req = len(target_skills)
        skill_score = (len(matched) / total_req * 100.0) if total_req > 0 else 70.0

        # Stage 3: Experience match
        exp_score = 90.0 if candidate.years_of_experience >= (job.experience_required or 0) else 60.0

        # Stage 4: Location match
        loc_score = 80.0

        # Overall weighted match calculation
        overall = (skill_score * 0.4) + (exp_score * 0.3) + (loc_score * 0.15) + (sponsorship_score * 0.15)

        explanation = (
            f"Matched {len(matched)} key skills ({', '.join(matched) if matched else 'None'}). "
            f"Candidate has {candidate.years_of_experience} yrs experience vs requirement. "
            f"Visa sponsorship status: {job.visa_sponsorship.status.value}."
        )

        return MatchResult(
            job_id=job.id or "unknown",
            job_title=job.title,
            company=job.company,
            overall_match=round(overall, 1),
            skill_match=round(skill_score, 1),
            experience_match=round(exp_score, 1),
            location_match=round(loc_score, 1),
            sponsorship_match=round(sponsorship_score, 1),
            matched_skills=matched,
            missing_skills=missing,
            passed_hard_filters=passed,
            explanation=explanation,
        )
