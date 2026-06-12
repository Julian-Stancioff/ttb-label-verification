"""Configuration loaded from environment / .env file."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (parent of backend/) if present, then CWD.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv()  # also pick up a .env in the current working directory / real env


class Settings:
    def __init__(self) -> None:
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.openrouter_base_url = os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/")
        self.llm_model = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4.5").strip()
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "8000"))
        # Bounded concurrency for batch requests so big batches stay responsive.
        self.batch_concurrency = int(os.getenv("BATCH_CONCURRENCY", "8"))
        # Per-label model timeout (seconds). Keeps us inside the 5s UX budget.
        self.request_timeout = float(os.getenv("REQUEST_TIMEOUT", "20"))
        # Persistent data dir: SQLite DB + stored label images for the review queue.
        # In the container this is a mounted volume (default /data); locally ./data.
        default_data = "/data" if Path("/data").is_dir() else str(_PROJECT_ROOT / "data")
        self.data_dir = Path(os.getenv("DATA_DIR", default_data))

    @property
    def configured(self) -> bool:
        return bool(self.openrouter_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
