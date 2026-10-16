from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Meridian"

    database_url: str = "postgresql+asyncpg://localhost:5432/meridian"

    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True

    source_cache_ttl_seconds: int = 300
    space_snapshot_cache_ttl_seconds: int = 300
    shelf_cache_ttl_seconds: int = 300
    rate_limit_per_second: int = 10
    rate_limit_burst: int = 20

    circuit_failure_threshold: int = 5
    circuit_recovery_seconds: int = 30
    circuit_fail_window_seconds: int = 60
    
    api_key: str | None = None
    url: str | None = None
    model: str | None = None

    siliconflow_api_key: str | None = None
    mineru_token: str | None = None
    bge_model_path: str | None = None

    ragas_api_key: str | None = None
    ragas_base_url: str | None = None
    ragas_llm_model: str | None = None
    eval_username: str = "meridian"

    port: int = 8897
    allowed_origins: str = (
        "http://localhost:5180,http://127.0.0.1:5180,"
        "http://localhost:8080,http://127.0.0.1:8080"
    )
    allow_private_urls: bool = False

    secret_key: str | None = None
    algorithm: str | None = None
    access_token_expire_minutes: int | None = None

    kafka_bootstrap_servers: str = "localhost:9092"
    topic_add_source: str = "add.source"
    topic_add_source_retry: str = "add.source.retry"
    topic_add_source_dlq: str = "add.source.dlq"

    source_consumer: str = "source"

settings = Settings()
