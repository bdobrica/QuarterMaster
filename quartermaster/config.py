"""Environment-only configuration; importing this module touches no disk."""

from pathlib import Path

from pydantic import HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QM_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    builder_base_url: HttpUrl | None = None
    builder_model: str | None = None
    builder_api_key: SecretStr | None = None

    @field_validator("builder_base_url", "builder_model", "builder_api_key", mode="before")
    @classmethod
    def empty_is_unconfigured(cls, value):
        return None if value == "" else value

    @property
    def database_path(self) -> Path:
        return self.data_dir / "quartermaster.sqlite3"

    @property
    def artifact_root(self) -> Path:
        return self.data_dir / "artifacts"


def initialize_storage(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.artifact_root.mkdir(exist_ok=True, mode=0o700)
