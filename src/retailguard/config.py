from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://retailguard:retailguard@localhost:5432/retailguard"
    )
    mock_api_url: str = "http://localhost:8000"
    pii_hash_salt: str = "retailguard-demo-only"
    retailguard_project_root: Path = Path(".")
    retailguard_data_root: Path = Path("data")

    gcp_project_id: str = "retailguard-data-platform"
    gcp_location: str = "asia-southeast1"
    gcs_bucket: str = "retailguard-data-platform-111122397706"
    bigquery_dataset: str = "retailguard"
    bigquery_maximum_bytes_billed: int = 104_857_600

    @property
    def data_root(self) -> Path:
        return self.retailguard_data_root.resolve()

    @property
    def project_root(self) -> Path:
        return self.retailguard_project_root.resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
