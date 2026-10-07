from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.api.deps import get_job_recheck_service, get_searxng, get_llm
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.core.config import settings
from ai_service.app.database.session import get_db
from ai_service.app.models.job import JobModel
from ai_service.app.repositories.candidate_repository import CandidateRepository
from ai_service.app.repositories.connection_repository import ConnectionRepository
from ai_service.app.repositories.job_repository import JobRepository
from ai_service.app.schemas.match import JobWithMatch
from ai_service.app.services.jobs.recheck_service import JobRecheckService
from ai_service.app.services.matching.matching_engine import MatchingEngineService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobWithMatch])
async def list_jobs(
    limit: int = Query(200, ge=1, le=1000),
    include_closed: bool = Query(False, description="Also return postings the job board reported closed"),
    hidden: bool = Query(False, description="Only the jobs you marked not interested"),
    db: AsyncSession = Depends(get_db),
):
    """Stored jobs, best match first. Hidden jobs and companies you blocked are left out."""
    return await JobRepository(db).list_all(limit, include_closed, await _blocked(db), hidden)


@router.post("/{job_id}/hide", status_code=204)
async def hide_job(job_id: str, db: AsyncSession = Depends(get_db)) -> None:
    """Not interested: hide this job now and in future search results."""
    if not await JobRepository(db).set_hidden(job_id, True):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")


@router.post("/{job_id}/unhide", status_code=204)
async def unhide_job(job_id: str, db: AsyncSession = Depends(get_db)) -> None:
    if not await JobRepository(db).set_hidden(job_id, False):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

def _format_profile(r: dict) -> dict | None:
    url = r.get("url", "")
    title = r.get("title", "")
    content = r.get("content", "")
    
    if "linkedin.com" not in url or "linkedin.com/company" in url or "linkedin.com/jobs" in url or "linkedin.com/school" in url:
        return None
    
    clean_title = title.replace(" | LinkedIn", "").replace(" - LinkedIn", "").strip()
    if not clean_title:
        return None

    return {
        "title": clean_title,
        "url": url,
        "snippet": content
    }


@router.get("/company-contacts")
async def get_company_contacts(company: str = Query(...), db: AsyncSession = Depends(get_db), searcher = Depends(get_searxng)):
    candidate = await CandidateRepository(db).get_active()
    connections = []
    if candidate:
        connections_list = await ConnectionRepository(db).find_by_company(candidate.id, company)
        connections = [{"first_name": c.first_name, "last_name": c.last_name, "position": c.position} for c in connections_list]
        
    recruiters = []
    employees = []
    try:
        # Search recruiters & HR profiles on LinkedIn
        query_hr = f'site:linkedin.com/in "{company}" ("Talent Acquisition" OR "Recruiter" OR "HR")'
        results_hr = await searcher.search(query_hr)
        for r in results_hr:
            item = _format_profile(r)
            if item and len(recruiters) < 6:
                recruiters.append(item)
            
        # Search employees & team members on LinkedIn
        query_emp = f'site:linkedin.com/in "{company}" ("Software Engineer" OR "AI" OR "Developer" OR "Manager")'
        results_emp = await searcher.search(query_emp)
        for r in results_emp:
            item = _format_profile(r)
            if item and len(employees) < 6:
                employees.append(item)
    except Exception as e:
        import logging
        logging.getLogger("jobpilot").warning(f"X-Ray contact search failed: {e}")
        
    return {
        "company": company,
        "linkedin_search_hr": f"https://www.linkedin.com/search/results/people/?keywords={company}%20Recruiter%20Talent%20Acquisition%20HR",
        "linkedin_search_emp": f"https://www.linkedin.com/search/results/people/?keywords={company}%20Software%20Engineer%20AI%20Manager",
        "connections": connections,
        "recruiters": recruiters,
        "employees": employees
    }


@router.get("/{job_id}/insiders")
async def get_insiders(job_id: str, db: AsyncSession = Depends(get_db), searcher = Depends(get_searxng)):
    job = await db.get(JobModel, job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return await get_company_contacts(company=job.company, db=db, searcher=searcher)


async def _blocked(db: AsyncSession) -> list[str]:
    candidate = await CandidateRepository(db).get_active()
    return candidate.preferences.blocked_companies if candidate else []


@router.post("/rescore", response_model=list[JobWithMatch])
async def rescore_jobs(limit: int = Query(200, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    """Re-run matching for every stored job (e.g. after the profile changed); returns the top `limit`."""
    repo = JobRepository(db)
    candidate = await CandidateRepository(db).get_active()
    if candidate is not None:
        matcher = MatchingEngineService()
        async for batch in repo.iter_batches():
            await repo.upsert_many(
                [JobWithMatch(job=i.job, match=matcher.evaluate_match(candidate, i.job)) for i in batch]
            )
    return await repo.list_all(limit, blocked_companies=await _blocked(db))


@router.post("/recheck")
async def recheck_jobs(
    limit: int | None = Query(None, ge=1, le=500, description="Jobs to check (default: JOB_RECHECK_BATCH_SIZE)"),
    force: bool = Query(False, description="Also re-check jobs that were checked recently"),
    service: JobRecheckService = Depends(get_job_recheck_service),
) -> dict[str, int]:
    """Ask the job boards whether stored postings are still open; closed ones are hidden from the list."""
    return await service.recheck_stale(limit or settings.job_recheck_batch_size, 0 if force else None)


@router.post("/outreach-message")
async def generate_outreach_message(
    body: dict,
    db: AsyncSession = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
):
    company = body.get("company", "Target Company")
    contact_name = body.get("contact_name", "Hiring Manager")
    contact_role = body.get("contact_role", "Recruiter")
    job_title = body.get("job_title", "Software Engineer")
    
    candidate = await CandidateRepository(db).get_active()
    cand_name = candidate.name if candidate else "Candidate"
    cand_skills = ", ".join(candidate.skills[:8]) if candidate else "Software Engineering"
    cand_exp = candidate.years_of_experience if candidate else 1
    cand_role = candidate.current_role or "Software Engineer"
    
    system_prompt = "You are a top tech recruiter and career coach. Always respond in valid JSON matching the requested schema."
    user_prompt = f"""
    Write personalized cold outreach messages for candidate {cand_name} (Current Role: {cand_role}, {cand_exp} years experience, Core Skills: {cand_skills}):
    Target Company: {company}
    Contact Person Name/Role: {contact_name} ({contact_role})
    Target Role: {job_title}
    
    Provide JSON output with exact keys:
    - "linkedin_note": A 280-character maximum concise LinkedIn connection invite note.
    - "email_message": A 150-word direct email/message requesting a brief chat or referral for the target role.
    """
    
    return await llm.complete_json(system_prompt, user_prompt)

