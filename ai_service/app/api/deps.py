"""Process-wide service singletons exposed as FastAPI dependencies."""

from functools import lru_cache

from ai_service.app.agents.application_agent.graph import ApplicationAgent
from ai_service.app.agents.search_agent.graph import SearchAgent
from ai_service.app.core.config import settings
from ai_service.app.database.session import AsyncSessionLocal
from ai_service.app.integrations.llm.llm_client import LLMClient
from ai_service.app.integrations.mail.imap_reader import ImapReader
from ai_service.app.integrations.search.searxng_client import SearXNGClient
from ai_service.app.services.applications.application_service import ApplicationService
from ai_service.app.services.applications.tailoring_service import ApplicationTailoringService
from ai_service.app.services.inbox.inbox_service import InboxService
from ai_service.app.services.jobs.enrichment_service import JobEnrichmentService
from ai_service.app.services.jobs.recheck_service import JobRecheckService
from ai_service.app.services.notifications.webhook_service import WebhookNotificationService
from ai_service.app.services.resume.resume_parser import ResumeParserService
from ai_service.app.services.screening.answer_bank import ScreeningSuggester
from ai_service.app.services.search.board_source import BoardSearchSource
from ai_service.app.services.search.discovery_service import DiscoveryService
from ai_service.app.services.search.search_service import SearchService
from ai_service.app.services.tasks.runner import PeriodicJob, TaskRunner


@lru_cache
def get_llm() -> LLMClient:
    return LLMClient()


@lru_cache
def get_searxng() -> SearXNGClient:
    return SearXNGClient(settings.searxng_url, settings.searxng_timeout_seconds)


@lru_cache
def get_board_source() -> BoardSearchSource:
    return BoardSearchSource(settings.data_dir / "boards.json")


@lru_cache
def get_search_agent() -> SearchAgent:
    service = SearchService(get_searxng(), board_source=get_board_source())
    return SearchAgent(service, get_llm(), enricher=JobEnrichmentService())


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
def get_inbox_service() -> InboxService:
    reader = None
    if settings.inbox_enabled:
        reader = ImapReader(
            settings.imap_host, settings.imap_port, settings.imap_user, settings.imap_password, settings.imap_folder
        )
    return InboxService(AsyncSessionLocal, reader, notifier=get_notifier())


@lru_cache
def get_discovery_service() -> DiscoveryService:
    return DiscoveryService(AsyncSessionLocal, get_search_agent, get_notifier())


@lru_cache
def get_task_runner() -> TaskRunner:
    """The process-wide background worker: queued agent tasks plus periodic jobs."""
    service = get_application_service()
    periodic = []
    if settings.inbox_enabled and settings.inbox_check_interval_minutes > 0:
        inbox = get_inbox_service()
        periodic.append(
            PeriodicJob(
                "inbox", settings.inbox_check_interval_minutes * 60, inbox.check_if_configured, initial_delay=90
            )
        )
    if settings.discovery_interval_hours > 0:
        discovery = get_discovery_service()
        periodic.append(
            PeriodicJob("discovery", settings.discovery_interval_hours * 3600, discovery.run_quietly, initial_delay=300)
        )
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
