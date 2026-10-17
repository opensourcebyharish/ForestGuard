"""Validated application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration; secrets are deliberately not part of public responses."""

    model_config = SettingsConfigDict(
        env_prefix="FORESTGUARD_",
        env_file=(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ForestGuard"
    environment: str = "development"
    database_path: Path = Path("data/forestguard.sqlite3")
    cors_origins: list[str] = ["http://localhost:5173"]
    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_min_severity: str = "WARNING"
    telegram_timeout_seconds: float = 5.0
    telegram_retries: int = 2
    device_commands_enabled: bool = False
    device_commands_auth_token: str | None = None
    device_commands_operator_id: str = "configured_operator"
    device_command_rate_limit: int = 10
    device_command_rate_window_seconds: int = 60
    device_command_max_expiry_seconds: int = 3600

    @field_validator("database_path", mode="before")
    @classmethod
    def resolve_database_path(cls, value: str | Path) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else PROJECT_ROOT / path

    @field_validator("app_name", "environment")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value.strip()

    @field_validator("telegram_bot_token", "telegram_chat_id", mode="before")
    @classmethod
    def empty_telegram_credentials_are_missing(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None

    @field_validator("telegram_min_severity")
    @classmethod
    def validate_telegram_severity(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"WATCH", "WARNING", "CRITICAL"}:
            raise ValueError("telegram_min_severity must be WATCH, WARNING, or CRITICAL")
        return normalized

    @field_validator("telegram_timeout_seconds")
    @classmethod
    def validate_telegram_timeout(cls, value: float) -> float:
        if not 0.1 <= value <= 30:
            raise ValueError("telegram_timeout_seconds must be between 0.1 and 30")
        return value

    @field_validator("telegram_retries")
    @classmethod
    def validate_telegram_retries(cls, value: int) -> int:
        if not 0 <= value <= 5:
            raise ValueError("telegram_retries must be between 0 and 5")
        return value

    @field_validator("device_commands_auth_token", mode="before")
    @classmethod
    def empty_command_token_is_missing(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = str(value).strip()
        return token or None

    @field_validator("device_commands_operator_id")
    @classmethod
    def validate_operator_id(cls, value: str) -> str:
        operator_id = value.strip()
        if not operator_id or len(operator_id) > 64:
            raise ValueError("device_commands_operator_id must contain 1 to 64 characters")
        return operator_id

    @field_validator("device_command_rate_limit")
    @classmethod
    def validate_command_rate_limit(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError("device_command_rate_limit must be between 1 and 100")
        return value

    @field_validator("device_command_rate_window_seconds")
    @classmethod
    def validate_command_rate_window(cls, value: int) -> int:
        if not 1 <= value <= 3600:
            raise ValueError("device_command_rate_window_seconds must be between 1 and 3600")
        return value

    @field_validator("device_command_max_expiry_seconds")
    @classmethod
    def validate_command_max_expiry(cls, value: int) -> int:
        if not 30 <= value <= 86400:
            raise ValueError("device_command_max_expiry_seconds must be between 30 and 86400")
        return value

    @property
    def telegram_available(self) -> bool:
        return self.telegram_enabled and bool(self.telegram_bot_token and self.telegram_chat_id)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
