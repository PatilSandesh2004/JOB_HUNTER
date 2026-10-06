"""Process-wide service singletons exposed as FastAPI dependencies."""

from functools import lru_cache

from ai_service.app.agents.application_agent.graph import ApplicationAgent
from ai_service.app.agents.search_agent.graph import SearchAgent
from ai_service.app.core.config import settings
from ai_service.app.database.session import AsyncSessionLocal
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.integrations.search.searxng_client import SearXNGClient
from ai_service.app.services.applications.application_service import ApplicationService
from ai_service.app.services.applications.tailoring_service import ApplicationTailoringService
from ai_service.app.services.jobs.enrichment_service import JobEnrichmentService
from ai_service.app.services.jobs.recheck_service import JobRecheckService
from ai_service.app.services.notifications.webhook_service import WebhookNotificationService
from ai_service.app.services.resume.resume_parser import ResumeParserService
from ai_service.app.services.screening.answer_bank import ScreeningSuggester
from ai_service.app.services.search.board_source import BoardSearchSource
from ai_service.app.services.search.search_service import SearchService
from ai_service.app.services.tasks.runner import PeriodicJob, TaskRunner


@lru_cache
def get_llm() -> LLMClient:
    return LLMClient()


@lru_cache
def get_searxng() -> SearXNGClient:
    return SearXNGClient(settings.searxng_url, settings.searxng_timeout_seconds)


@lru_cache
def get_search_agent() -> SearchAgent:
    boards = BoardSearchSource(settings.data_dir / "boards.json")
    return SearchAgent(SearchService(get_searxng(), board_source=boards), get_llm(), enricher=JobEnrichmentService())


@lru_cache
def get_resume_parser() -> ResumeParserService:
    return ResumeParserService(get_llm())


@lru_cache
def get_notifier() -> WebhookNotificationService:
    return WebhookNotificationService(settings.notification_webhook_url, settings.high_match_threshold)


@lru_cache
def get_application_service() -> ApplicationService:
    return ApplicationService(
        AsyncSessionLocal,
        agent_factory=lambda: ApplicationAgent(ApplicationTailoringService(get_llm())),
        suggester=ScreeningSuggester(get_llm()),
    )


@lru_cache
def get_job_recheck_service() -> JobRecheckService:
    return JobRecheckService(AsyncSessionLocal, JobEnrichmentService())


@lru_cache
def get_task_runner() -> TaskRunner:
    """The process-wide background worker: queued agent tasks plus periodic job re-checks."""
    service = get_application_service()
    periodic = []
    if settings.job_recheck_interval_hours > 0:
        recheck = get_job_recheck_service()
        periodic.append(
            PeriodicJob(
                "job-recheck",
                settings.job_recheck_interval_hours * 3600,
                lambda: recheck.recheck_stale(settings.job_recheck_batch_size),
            )
        )
    runner = TaskRunner(
        AsyncSessionLocal,
        service.task_handlers(),
        concurrency=settings.task_concurrency,
        poll_seconds=settings.task_poll_seconds,
        backoff_seconds=settings.task_retry_backoff_seconds,
        periodic=periodic,
    )
    service.on_enqueue = runner.notify
    return runner
