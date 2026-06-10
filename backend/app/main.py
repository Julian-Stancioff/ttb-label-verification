"""FastAPI application entry point.

Provides the health check and serves the static frontend. Extraction and
verification endpoints (``/verify``, ``/verify/batch``) are added by separate
beads — this module just wires up the app skeleton, CORS, and static mount.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings

app = FastAPI(title="TTB Label Verification", version="0.1.0")

# Permissive CORS: this is a single-purpose internal prototype served from the
# same origin as the frontend; loosen rather than block during the build.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


# Serve the static frontend at the root if it exists. The directory may not be
# present yet (built by a separate bead); mount it only when available so the
# app still boots for backend-only work.
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")


def main() -> None:
    """Run the app with uvicorn (``python -m app.main``)."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
