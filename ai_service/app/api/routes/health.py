from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.api.deps import get_llm, get_searxng
from ai_service.app.core.config import settings
from ai_service.app.database.session import get_db
from ai_service.app.integrations.browser.runtime import browser_health
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.integrations.search.searxng_client import SearXNGClient

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    db: AsyncSession = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
    searxng: SearXNGClient = Depends(get_searxng),
) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False
    searxng_ok = await searxng.healthcheck()
    browser = await browser_health()
    return {
        "service": "jobpilot-ai",
        "version": settings.app_version,
        "status": "ok" if database_ok else "degraded",
        "components": {
            "database": {"ok": database_ok, "driver": settings.database_url.split(":", 1)[0]},
            "searxng": {"ok": searxng_ok, "url": settings.searxng_url},
            "llm": {"ok": llm.available, "model": llm.primary_model if llm.available else None},
            "browser": {"ok": browser["ok"], "detail": browser["detail"], "headless": settings.browser_headless},
        },
    }
