"""FastAPI entrypoint for the JobPilot AI service."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ai_service.app.api.deps import get_application_service
from ai_service.app.api.routes import applications, candidates, health, jobs, search
from ai_service.app.core.config import REPO_ROOT, settings
from ai_service.app.core.errors import JobPilotError, LLMUnavailableError, NotFoundError, ResumeParseError
from ai_service.app.core.logging import configure_logging
from ai_service.app.core.security import require_token
from ai_service.app.database.session import init_db
from ai_service.app.services.applications.application_service import ApplicationConflictError

logger = logging.getLogger("jobpilot")

_ERROR_STATUS: dict[type[JobPilotError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ApplicationConflictError: status.HTTP_409_CONFLICT,
    ResumeParseError: 422,
    LLMUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    await init_db()
    recovered = await get_application_service().recover_interrupted()
    if recovered:
        logger.warning("Marked %d interrupted application(s) as FAILED", recovered)
    logger.info("JobPilot AI service ready (SearXNG: %s, LLM: %s)", settings.searxng_url, settings.llm_enabled)
    yield


app = FastAPI(title=f"{settings.app_name} AI Service", version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(JobPilotError)
async def handle_domain_error(_: Request, exc: JobPilotError) -> JSONResponse:
    code = next((c for t, c in _ERROR_STATUS.items() if isinstance(exc, t)), status.HTTP_400_BAD_REQUEST)
    return JSONResponse(status_code=code, content={"detail": str(exc)})


app.include_router(health.router, prefix=settings.api_v1_prefix)
for module in (search, jobs, candidates, applications):
    app.include_router(module.router, prefix=settings.api_v1_prefix, dependencies=[Depends(require_token)])

# The Go gateway is the primary UI host; serving it here too lets the AI service run standalone.
FRONTEND_DIR = REPO_ROOT / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")
