"""Type-safe settings via pydantic-settings.

OpenAI and SMTP degrade to local stand-ins when their keys are absent.
``get_settings`` returns a fresh instance (no cache) so tests can vary the
environment per case.
"""

from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    # OpenAI (extraction, summarisation, embeddings, ...)
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    # LLM cost guardrails: cap output tokens per call; truncate inbound message
    # so a huge paste can't inflate the extraction prompt.
    extraction_max_tokens: int = 256
    selection_max_tokens: int = 128
    max_message_chars: int = 2000

    # SMTP (confirmation email). Works with any provider incl. Mailgun SMTP.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    mail_from: str | None = None

    # Branding / scheduling for the email + calendar invite
    business_name: str = "Your Service Team"
    business_tz: str = "Australia/Brisbane"
    booking_duration_min: int = 60
    business_open_hour: int = 8  # availability search window (inclusive)
    business_close_hour: int = 17  # exclusive

    # HubSpot CRM (push the customer contact after the job is confirmed)
    hubspot_access_token: str | None = None
    hubspot_base_url: str = "https://api.hubapi.com"

    # --- Feature flags -------------------------------------------------------
    # Off → step degrades to dry-run even if a token is present, so the whole
    # flow can run standalone.
    feature_hubspot_sync: bool = True

    # LangSmith — tracing only. Set the key to turn tracing on.
    langsmith_api_key: str | None = None
    langsmith_project: str = "booking-agent"

    # Runtime / security
    environment: str = "development"
    log_level: str = "INFO"
    # CORS: comma-separated allowed origins. Wildcard is rejected in production
    # (see validator) and never paired with credentials.
    cors_origins: str = "http://localhost:3000"
    # Unset → open (dev/local); set to require Bearer auth on every /runs call.
    api_auth_token: str | None = None
    # Bounds the background run thread pool so a burst of starts can't spawn
    # unbounded threads / OpenAI calls.
    max_concurrent_runs: int = 8
    # Overall wall-clock budget for a synchronous graph invocation, so a wedged
    # node can't pin the request (only the LLM call is bounded on its own).
    graph_invocation_timeout_s: float = 60.0

    # Where the run state lives. Postgres → durable checkpointer (paused runs
    # survive a restart); SQLite/unset → in-process MemorySaver (dev).
    database_url: str = "sqlite:///./booking.db"
    # Redis for cross-replica fan-out: when set, the event bus and rate limiter
    # become shared (durable across replicas). Unset → in-process (single worker).
    redis_url: str | None = None

    # Database pool (Postgres). statement_timeout caps a single query so a slow
    # one can't pin a pooled connection indefinitely.
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800
    db_pool_timeout: int = 10
    db_statement_timeout_ms: int = 30000
    # Inbound rate limit on run submission (per client, fixed window). In-process.
    rate_limit_runs: int = 30
    rate_limit_window_s: int = 60

    @model_validator(mode="after")
    def _guard_cors_in_prod(self) -> Settings:
        # Fail fast: a wildcard CORS origin in production is an unsafe default.
        if self.is_production and "*" in self.cors_origin_list:
            raise ValueError(
                "CORS wildcard '*' is not allowed in production; set CORS_ORIGINS explicitly"
            )
        return self

    @model_validator(mode="after")
    def _require_auth_token_in_prod(self) -> Settings:
        # Fail closed: never run prod with auth disabled (an empty token opens
        # every /runs call). Dev (unset token) stays open.
        if self.is_production and not (self.api_auth_token or "").strip():
            raise ValueError(
                "API_AUTH_TOKEN must be set in production (auth cannot be disabled)"
            )
        return self

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.langsmith_api_key)

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def docs_enabled(self) -> bool:
        # Hide interactive docs in production.
        return not self.is_production

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cors_allow_credentials(self) -> bool:
        # Browsers reject credentialed requests against a wildcard origin.
        return "*" not in self.cors_origin_list

    @property
    def use_real_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.mail_from)

    @property
    def hubspot_configured(self) -> bool:
        return bool(self.hubspot_access_token)

    @property
    def hubspot_sync_enabled(self) -> bool:
        """Real CRM push only when the flag is on AND a token is set; otherwise dry-run."""
        return self.feature_hubspot_sync and self.hubspot_configured

    @property
    def is_postgres(self) -> bool:
        """Postgres DB → durable LangGraph checkpointer; else in-process MemorySaver."""
        return self.database_url.startswith(("postgres://", "postgresql://"))

    @property
    def redis_enabled(self) -> bool:
        """Redis configured → shared event bus + rate limiter across replicas."""
        return bool(self.redis_url)


def get_settings() -> Settings:
    return Settings()
