"""Runtime settings, read from environment variables or a local .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = PROJECT_ROOT / "assets"
SAMPLES_DIR = PROJECT_ROOT / "samples"
TEMPLATES_DIR = PROJECT_ROOT / "templates"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    model: str = Field(default="claude-opus-5-5", alias="PITCH90_MODEL")
    effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        default="high", alias="PITCH90_EFFORT"
    )
    fallbacks: Literal["default", "off"] = Field(default="default", alias="PITCH90_FALLBACKS")
    timeout_seconds: float = Field(default=300.0, alias="PITCH90_TIMEOUT_SECONDS")
    max_visual_pages: int = Field(default=12, alias="PITCH90_MAX_VISUAL_PAGES")
    max_upload_mb: int = Field(default=50, alias="PITCH90_MAX_UPLOAD_MB")
    max_pages: int = Field(default=150, alias="PITCH90_MAX_PAGES")
    words_per_minute: int = Field(default=140, alias="PITCH90_WORDS_PER_MINUTE")
    soffice_path: str | None = Field(default=None, alias="PITCH90_SOFFICE_PATH")
    report_template: Path | None = Field(default=None, alias="PITCH90_REPORT_TEMPLATE")
    # Web deployment: sign-in gate and spend throttle.
    app_password: SecretStr | None = Field(default=None, alias="APP_PASSWORD")
    app_username: str = Field(default="ten", alias="APP_USERNAME")
    max_concurrent_analyses: int = Field(default=2, alias="PITCH90_MAX_CONCURRENT")
    railway_environment: str | None = Field(default=None, alias="RAILWAY_ENVIRONMENT")

    # Result emails via Resend: off unless RESEND_API_KEY is set.
    resend_api_key: SecretStr | None = Field(default=None, alias="RESEND_API_KEY")
    report_email_to: str = Field(default="Info@tencapital.group", alias="REPORT_EMAIL_TO")
    report_email_from: str = Field(
        default="TEN Capital Pitch Analysis <pitch90@tencapital.group>", alias="REPORT_EMAIL_FROM",
        description="Must be on a domain verified with Resend.",
    )
    email_demo_runs: bool = Field(default=False, alias="EMAIL_DEMO_RUNS")

    @property
    def report_recipients(self) -> list[str]:
        return [a.strip() for a in self.report_email_to.split(",") if a.strip()]

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key and self.resend_api_key.get_secret_value().strip()
                    and self.report_recipients)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.app_password and self.app_password.get_secret_value())

    @property
    def has_api_key(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value().strip())

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
