from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application-wide configuration.
    Values are loaded from environment variables and .env.
    """

    app_name: str = "JobPilot"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Search Engine
    searxng_url: str = "http://localhost:8080"

    # Primary Database (SQLite fallback for dev, PostgreSQL async for prod)
    database_url: str = "sqlite+aiosqlite:///./jobpilot.db"

    # Cache & Messaging
    redis_url: str = "redis://localhost:6379/0"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    # Vector DB
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # Object Storage
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"

    # LLM Settings (Groq API)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()