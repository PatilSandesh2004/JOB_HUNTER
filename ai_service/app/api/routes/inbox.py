from typing import Any

from fastapi import APIRouter, Depends

from ai_service.app.api.deps import get_inbox_service
from ai_service.app.services.inbox.inbox_service import InboxService

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get("")
async def inbox_status(service: InboxService = Depends(get_inbox_service)) -> dict[str, Any]:
    """Whether the job-alert inbox is set up, the last check, and recent alerts / status updates."""
    return await service.status()


@router.post("/check")
async def check_inbox(service: InboxService = Depends(get_inbox_service)) -> dict[str, Any]:
    """Read new job-alert emails and employer replies now."""
    return await service.check()
