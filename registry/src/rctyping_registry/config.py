"""Registry server configuration using pydantic-settings."""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class RegistrySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RCTYPING_REGISTRY_",
        env_file=".env",
        extra="ignore",
    )

    data_dir: Path = Path("./data/registry")
    host: str = "0.0.0.0"
    port: int = 8001
    key_passphrase: Optional[str] = None
    admin_token: str = "dev-admin-secret"


registry_settings = RegistrySettings()
