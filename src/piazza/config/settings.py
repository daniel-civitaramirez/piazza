"""Application settings loaded from environment variables."""

from pydantic import field_validator
from pydantic_settings import BaseSettings

from piazza.core.currency import normalize as _normalize_currency

# Approval status constants
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Admin
    admin_jid: str = ""

    # Evolution API
    evo_api_key: str = ""
    evo_api_url: str = "http://localhost:8080"
    evo_instance_name: str = "piazza-main"
    bot_jid: str = ""
    bot_lid: str = ""
    discover_bot_lid: bool = False  # enable once to log BOT_LID, then set BOT_LID and disable

    # Database
    supabase_db_url: str = "sqlite+aiosqlite://"

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_password: str = ""

    # LLM
    anthropic_api_key: str = ""
    opensource_agent_enabled: bool = True
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:4b"
    ollama_timeout: float = 10.0
    claude_model: str = "claude-haiku-4-5-20251001"
    claude_timeout: float = 15.0
    claude_max_tokens: int = 1024
    llm_temperature: float = 0.0

    # Security
    encryption_key: str = ""
    webhook_secret: str = ""
    injection_patterns_path: str = "config/injection_patterns.json"

    # Circuit breaker
    circuit_breaker_failures: int = 3
    circuit_breaker_window: int = 120
    circuit_breaker_cooldown: int = 600

    # Rate limiting
    group_rate_limit_per_minute: int = 5

    # Input validation
    max_message_length: int = 2000
    default_currency: str = "EUR"

    # FX (openexchangerates.org)
    openexchangerates_key: str = ""
    fx_cache_ttl_seconds: int = 3600

    # WhatsApp client
    wa_send_max_retries: int = 3
    wa_send_backoff_base: float = 0.5
    wa_client_timeout: float = 10.0
    health_check_timeout: float = 5.0

    # Agent
    conversation_context_limit: int = 20
    message_log_retention_multiplier: int = 2

    # Worker
    worker_max_jobs: int = 10
    worker_job_timeout: int = 30
    group_lock_timeout: int = 33
    group_lock_wait: int = 10
    reminder_cron_seconds: str = "0,30"

    # Monitoring (optional)
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1

    @field_validator("default_currency")
    @classmethod
    def _validate_default_currency(cls, v: str) -> str:
        return _normalize_currency(v)

    @property
    def encryption_key_bytes(self) -> bytes:
        """Return the encryption key decoded from base64."""
        import base64

        return base64.b64decode(self.encryption_key)

    @property
    def reminder_cron_seconds_set(self) -> set[int]:
        """Parse comma-separated cron seconds string into a set."""
        return {int(s.strip()) for s in self.reminder_cron_seconds.split(",")}


settings = Settings()
