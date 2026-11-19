"""Application configuration using pydantic-settings."""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RCTYPING_",
        env_file=".env",
        extra="ignore",
    )

    data_dir: Path = Path("./data")
    host: str = "0.0.0.0"
    port: int = 8000
    key_passphrase: Optional[str] = None
    registry_url: Optional[str] = "http://localhost:8001"
    publish_default: bool = True
    corpus_dir: Path = Path(__file__).resolve().parent.parent.parent.parent / "corpus" / "data"

    # Wall clock skew allowance between client finish timestamp and server finish timestamp (in ms)
    max_clock_skew_ms: int = 4000
    # Minimum keystroke interval in ms (0.0 disables the upper WPM speed cap for limitless top WPM)
    min_human_iki_ms: float = 0.0
    # Minimum standard deviation of keystroke intervals (in ms) to detect uniform loop bots
    min_iki_stddev_ms: float = 4.0


settings = AppSettings()
