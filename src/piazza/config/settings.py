"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Evolution API
    evo_api_key: str = ""
    evo_api_url: str = "http://localhost:8080"
    evo_instance_name: str = "piazza-main"
    bot_jid: str = ""

    # Database
    supabase_db_url: str = "sqlite+aiosqlite://"

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_password: str = ""

    # LLM
    anthropic_api_key: str = ""
    ollama_url: str = "http://localhost:11434"

    # Security
    encryption_key: str = ""
    webhook_secret: str = ""
    injection_patterns_path: str = "config/injection_patterns.json"

    # External APIs (optional)
    openexchangerates_key: str = ""

    # Monitoring (optional)
    sentry_dsn: str = ""

    @property
    def encryption_key_bytes(self) -> bytes:
        """Return the encryption key decoded from base64."""
        import base64

        return base64.b64decode(self.encryption_key)


settings = Settings()
