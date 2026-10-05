from typing import Dict, Any, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from ai_service.app.agents.application_agent.graph import create_application_graph

router = APIRouter(prefix="/applications", tags=["applications"])


class ApplyRequest(BaseModel):
    candidate_id: str
    job_id: str
    application_url: str
    applicant_data: Dict[str, Any]
    human_approved: bool = False
    auto_submit: bool = False


@router.post("/apply")
async def start_or_submit_application(request: ApplyRequest):
    try:
        graph = create_application_graph()
        initial_state = {
            "candidate_id": request.candidate_id,
            "job_id": request.job_id,
            "application_url": request.application_url,
            "applicant_data": request.applicant_data,
            "cover_letter": request.applicant_data.get("cover_letter"),
            "tailored_resume": None,
            "auto_submit": request.auto_submit,
            "status": "DISCOVERED",
            "human_approved": request.human_approved or request.auto_submit,
            "confirmation": None,
        }
        
        final_state = await graph.ainvoke(initial_state)
        return {
            "candidate_id": request.candidate_id,
            "job_id": request.job_id,
            "application_url": request.application_url,
            "status": final_state.get("status"),
            "auto_submitted": request.auto_submit,
            "confirmation": final_state.get("confirmation") or "Application processed successfully.",
            "human_approval_required": not (request.human_approved or request.auto_submit),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Application workflow error: {str(e)}",
        )
