"""Environment-only configuration; importing this module touches no disk."""

from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QM_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    builder_base_url: HttpUrl | None = None
    builder_model: str | None = None
    builder_api_key: SecretStr | None = None
    builder_api_key_file: Path | None = None
    builder_timeout_seconds: float = Field(default=20, ge=1, le=30)
    local_base_url: HttpUrl | None = None
    local_model_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    local_timeout_seconds: float = Field(default=120, ge=1, le=180)
    candidate_base_url: HttpUrl = HttpUrl("http://candidate:8080")

    @field_validator(
        "builder_base_url",
        "builder_model",
        "builder_api_key",
        "builder_api_key_file",
        "local_base_url",
        "local_model_sha256",
        mode="before",
    )
    @classmethod
    def empty_is_unconfigured(cls, value):
        return None if value == "" else value

    @field_validator("builder_base_url")
    @classmethod
    def provider_url(cls, value):
        if value is not None:
            if value.username or value.password or value.query or value.fragment:
                raise ValueError("Provider URL cannot contain credentials, query or fragment")
            if value.scheme != "https" and value.host not in {"localhost", "127.0.0.1", "[::1]"}:
                raise ValueError("Use HTTPS for remote providers")
        return value

    @field_validator("local_base_url", "candidate_base_url")
    @classmethod
    def local_url(cls, value):
        if value is not None and (
            value.scheme != "http"
            or value.host not in {"localhost", "127.0.0.1", "[::1]", "inference", "candidate"}
            or value.username
            or value.password
            or value.query
            or value.fragment
        ):
            raise ValueError("Use HTTP on loopback or the local Compose inference service")
        return value

    @field_validator("builder_model")
    @classmethod
    def model_name(cls, value):
        if value is not None and (not value.strip() or len(value) > 200):
            raise ValueError("Set a model name of at most 200 characters")
        return value

    @property
    def database_path(self) -> Path:
        return self.data_dir / "quartermaster.sqlite3"

    @property
    def artifact_root(self) -> Path:
        return self.data_dir / "artifacts"


def initialize_storage(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.artifact_root.mkdir(exist_ok=True, mode=0o700)
