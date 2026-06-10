"""Configuration loading.

Reads settings from the environment, populated from a local ``.env`` file
(see ``.env.example``). ``.env`` is gitignored and never committed.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

# Load .env once at import time. We look for a .env next to the repo root
# (two levels up from this file: backend/app/config.py -> repo root) and also
# fall back to the process working directory.
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()  # also honor a .env in the cwd, without overriding the above


class Settings(BaseModel):
    """Runtime settings sourced from the environment."""

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "anthropic/claude-sonnet-4.5"
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def has_api_key(self) -> bool:
        return bool(self.openrouter_api_key)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings read from the environment."""
    return Settings(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_base_url=os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        llm_model=os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4.5"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
