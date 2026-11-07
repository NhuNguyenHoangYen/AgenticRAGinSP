"""Immutable logging settings, separate from model configuration."""
import logging
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LoggingConfig:
    directory: Path
    level: str = "INFO"
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5
    evaluation_enabled: bool = False
    evaluation_backup_count: int = 10
    environment: str = "development"
    app_version: str = "unknown"

    def __post_init__(self):
        if self.level not in logging._nameToLevel:
            raise ValueError("LOG_LEVEL must be a Python logging level")
        if self.max_bytes <= 0 or min(self.backup_count, self.evaluation_backup_count) < 1:
            raise ValueError("Log size and backup counts must be positive")

    @classmethod
    def from_env(cls):
        directory = Path(os.getenv("LOG_DIR", "logs")).expanduser()
        if not directory.is_absolute():
            directory = Path(__file__).resolve().parents[2] / directory
        return cls(
            directory=directory,
            level=os.getenv("LOG_LEVEL", "INFO").upper(),
            max_bytes=int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024))),
            backup_count=int(os.getenv("LOG_BACKUP_COUNT", "5")),
            evaluation_enabled=os.getenv("EVALUATION_CAPTURE_ENABLED", "false").lower() == "true",
            evaluation_backup_count=int(os.getenv("EVALUATION_BACKUP_COUNT", "10")),
            environment=os.getenv("APP_ENV", "development"),
            app_version=os.getenv("APP_VERSION", "unknown"),
        )
