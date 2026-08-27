from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    environment: str
    host: str
    port: int
    timezone: str
    data_dir: Path
    master_key: str
    session_secret: str
    first_run_setup: bool


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> AppConfig:
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        environment=os.getenv("APP_ENV", "production"),
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "3080")),
        timezone=os.getenv("TZ", "Europe/London"),
        data_dir=data_dir,
        master_key=os.getenv("AT_MASTER_KEY", ""),
        session_secret=os.getenv("SESSION_SECRET", ""),
        first_run_setup=_as_bool(os.getenv("FIRST_RUN_SETUP"), True),
    )


CONFIG = load_config()
