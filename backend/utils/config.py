"""
config.py
---------
Centralized configuration loaded from environment variables / .env.
Every module imports `settings` from here instead of calling os.getenv
directly, so defaults and validation live in one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: list[str]) -> list[str]:
    val = os.getenv(name)
    if not val:
        return default
    return [item.strip() for item in val.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # --- AI / Ollama ---
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")

    # --- App ---
    APP_ENV: str = os.getenv("APP_ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # --- Database ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./linuxpilot.db")

    # --- Safety ---
    # When False, COMMAND_EXECUTION intents are validated and explained
    # but never actually run. This is the master "dry run" switch and
    # should default to safe (disabled) in any new deployment.
    ALLOW_COMMAND_EXECUTION: bool = _bool("ALLOW_COMMAND_EXECUTION", False)
    ALLOWED_SERVICES: list[str] = field(
        default_factory=lambda: _list(
            "ALLOWED_SERVICES",
            ["docker", "apache2", "nginx", "ssh", "mysql", "postgresql"],
        )
    )
    COMMAND_TIMEOUT_SECONDS: int = int(os.getenv("COMMAND_TIMEOUT_SECONDS", "20"))


settings = Settings()
