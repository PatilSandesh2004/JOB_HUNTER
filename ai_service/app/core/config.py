"""Application-wide settings loaded from environment variables and the repo-root `.env`."""

from functools import cached_property
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "JobPilot"
    app_version: str = "0.2.0"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    # The UI is served same-origin by the gateway or this service, so only local origins need CORS.
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:8090",
            "http://127.0.0.1:8090",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]
    )
    # Shared secret for /api/v1/* (except /health). Empty disables the check; set it whenever the
    # service is reachable by anyone but you. The gateway checks the same API_TOKEN.
    api_token: str = ""

    # Storage
    database_url: str = f"sqlite+aiosqlite:///{(REPO_ROOT / 'data' / 'jobpilot.db').as_posix()}"
    data_dir: Path = REPO_ROOT / "data"
    max_resume_bytes: int = 10 * 1024 * 1024

    # Search
    searxng_url: str = "http://localhost:8080"
    searxng_timeout_seconds: float = 20.0
    searxng_max_concurrency: int = 4
    search_ats_targeting: bool = True
    search_enable_remotive: bool = True
    search_enable_arbeitnow: bool = True
    # Job sites searched through SearXNG (site: queries for the leading query only, to limit engine load).
    # Their postings are listed as "Apply manually": applying there needs your own login. [] disables.
    search_job_sites: list[str] = Field(default_factory=lambda: ["linkedin.com/jobs/view", "naukri.com", "indeed.com"])
    external_api_timeout_seconds: float = 10.0

    # LLM (Groq)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_models: list[str] = Field(default_factory=lambda: ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"])
    llm_temperature: float = 0.4
    llm_max_tokens: int = 2048
    llm_query_expansion: bool = True

    # Browser automation
    browser_headless: bool = True
    browser_timeout_ms: int = 30_000
    browser_max_concurrency: int = 2

    # Background agent tasks (database-backed queue, see services/tasks/runner.py)
    task_concurrency: int = 3
    task_poll_seconds: float = 2.0
    task_max_attempts: int = 3  # form fills; a fill is never retried once Submit was clicked
    task_retry_backoff_seconds: list[float] = Field(default_factory=lambda: [30.0, 120.0, 600.0])

    # Stored jobs are re-verified with their job board this often; closed postings are hidden (0 = off)
    job_recheck_interval_hours: float = 12.0
    job_recheck_batch_size: int = 40

    # Job-alert inbox (read-only IMAP). Gmail: imap.gmail.com with an app password (Google account ->
    # Security -> App passwords). Empty user/password disables it.
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    inbox_lookback_days: int = 7
    inbox_max_messages: int = 300
    inbox_check_interval_minutes: float = 30.0  # 0 = only when you click "Check now"
    inbox_update_statuses: bool = True  # move applications forward from employer emails
    inbox_resolve_tracking_links: bool = True  # follow alert-email redirect links to find the job URL

    # Run your profile's search automatically every N hours (0 = off)
    discovery_interval_hours: float = 0.0

    # Matching & notifications
    high_match_threshold: float = 85.0
    notification_webhook_url: str = ""

    @property
    def inbox_enabled(self) -> bool:
        return bool(self.imap_user and self.imap_password)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.groq_api_key) and self.groq_api_key != "your_groq_api_key_here"

    @cached_property
    def resumes_dir(self) -> Path:
        path = self.data_dir / "resumes"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @cached_property
    def screenshots_dir(self) -> Path:
        path = self.data_dir / "screenshots"
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
