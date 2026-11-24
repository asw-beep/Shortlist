"""Application settings, read from environment variables and an optional local .env file.

Precedence, highest first: real environment variables, then .env, then the defaults below.
The defaults match docker-compose.yml so a fresh clone runs without any setup, but real
deployments must set every secret through the environment.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repository root: relative data paths (config/, taxonomy/, sources/) resolve against it.
REPO_ROOT = Path(__file__).resolve().parents[3]

# Sign access tokens and feedback links on a laptop and in tests only. Staging and production
# refuse to start with them; anyone who reads this file could forge a token or a link.
LOCAL_JWT_SECRET = "local-development-only-jwt-secret-do-not-deploy"
LOCAL_LINK_SECRET = "local-development-only-link-secret-do-not-deploy"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # .env also holds POSTGRES_* variables meant for docker compose; ignore what we don't use.
        extra="ignore",
    )

    app_name: str = "Shortlist"
    environment: Literal["local", "test", "staging", "production"] = "local"
    api_prefix: str = "/api/v1"

    # postgresql+psycopg tells SQLAlchemy to use the psycopg 3 driver.
    database_url: str = "postgresql+psycopg://shortlist:shortlist@localhost:5432/shortlist"
    # True behind a transaction-mode pooler (Neon's pooled URL): psycopg must not prepare
    # statements, because the next statement may run on a different server connection.
    database_pooled: bool = False
    # Migrations need a real session, so they use the direct URL when one is set.
    direct_database_url: str | None = None
    # How long to wait for Postgres to accept a connection. libpq treats values below 2 as 2.
    db_connect_timeout_seconds: int = 3

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # True: one JSON object per line (containers, log tools). False: coloured console output.
    log_json: bool = True

    # Auth. SecretStr prints as '**********', so a key never lands in a log or a repr.
    jwt_secret_key: SecretStr = SecretStr(LOCAL_JWT_SECRET)
    jwt_issuer: str = "shortlist"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    password_reset_minutes: int = 30
    # Where reset emails and digest links land: the frontend.
    frontend_url: str = "http://localhost:5173"
    # Signs the one-click links in digest emails (HMAC-SHA256).
    feedback_link_secret: SecretStr = SecretStr(LOCAL_LINK_SECRET)

    # Third-party services. Unset means: that provider is skipped (LLMs) or kept in memory.
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    brevo_api_key: SecretStr | None = None
    email_from_address: str = "shortlist@example.com"
    email_from_name: str = "Shortlist"

    # Models. "<provider>:<model id>"; provisional until Phase 0 confirms the IDs.
    extract_models: list[str] = ["gemini:gemini-3.5-flash-lite", "groq:openai/gpt-oss-20b"]
    resume_model: str = "groq:openai/gpt-oss-120b"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_cache_dir: str | None = None

    # Data files, relative to the repository root.
    ranking_config_path: str = "config/ranking.yaml"
    taxonomy_path: str = "taxonomy/skills.yaml"
    boards_path: str = "sources/boards.yaml"

    # The largest request body the API reads at all: a 2 MB résumé PDF plus multipart wrapping.
    max_request_bytes: int = 3 * 1024 * 1024

    def repo_path(self, relative: str) -> Path:
        """A data path from settings, resolved against the repository root."""
        path = Path(relative)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def cookie_secure(self) -> bool:
        """Mark cookies Secure (HTTPS only) everywhere except a laptop and tests, which use http."""
        return self.environment in ("staging", "production")

    @property
    def deployed(self) -> bool:
        return self.environment in ("staging", "production")

    @model_validator(mode="after")
    def _check_secrets(self) -> Self:
        secret = self.jwt_secret_key.get_secret_value()
        if len(secret.encode()) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 bytes long")
        if self.deployed and secret == LOCAL_JWT_SECRET:
            raise ValueError(f"set JWT_SECRET_KEY: the built-in key is not for {self.environment}")
        if self.deployed:
            link_secret = self.feedback_link_secret.get_secret_value()
            if link_secret == LOCAL_LINK_SECRET:
                raise ValueError(
                    f"set FEEDBACK_LINK_SECRET: the built-in key is not for {self.environment}"
                )
            # An unset GitHub secret arrives as "", which would sign links with a known key.
            if len(link_secret.encode()) < 32:
                raise ValueError("FEEDBACK_LINK_SECRET must be at least 32 bytes long")
            if not self.frontend_url.startswith("https://"):
                raise ValueError(
                    "FRONTEND_URL must be the app's absolute https:// address when deployed"
                    " (digest and password-reset links are built from it)"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Build Settings once per process. Tests skip this and pass their own Settings."""
    return Settings()
