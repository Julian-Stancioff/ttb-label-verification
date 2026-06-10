"""FastAPI service: label verification API + static frontend."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .extraction import extract_label_fields
from .openrouter import OpenRouterError
from .verification import verify

app = FastAPI(title="TTB Label Verification", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _guess_mime(filename: Optional[str]) -> str:
    name = (filename or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith((".gif",)):
        return "image/gif"
    return "image/jpeg"


def _parse_application(application: Optional[str]) -> dict[str, Any]:
    if not application:
        return {}
    try:
        data = json.loads(application)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="`application` must be valid JSON.")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="`application` must be a JSON object.")
    return data


@app.get("/health")
async def health() -> dict[str, Any]:
    s = get_settings()
    return {"status": "ok", "model": s.llm_model, "configured": s.configured}


async def _verify_one(image_bytes: bytes, mime: str, expected: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    extracted = await extract_label_fields(image_bytes, mime)
    result = verify(expected, extracted)
    result["extracted"] = extracted
    result["elapsed_ms"] = round((time.perf_counter() - start) * 1000)
    return result


@app.post("/verify")
async def verify_label(
    image: UploadFile = File(...),
    application: Optional[str] = Form(None),
) -> JSONResponse:
    expected = _parse_application(application)
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="Uploaded image is empty.")
    try:
        result = await _verify_one(image_bytes, _guess_mime(image.filename), expected)
    except OpenRouterError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    result["filename"] = image.filename
    return JSONResponse(result)


@app.post("/verify/batch")
async def verify_batch(
    images: list[UploadFile] = File(...),
    applications: Optional[str] = Form(None),
) -> JSONResponse:
    """Verify many labels. `applications` is a JSON array; entries are matched to
    images by a `filename` key when present, otherwise by position."""
    apps_raw: list[dict[str, Any]] = []
    if applications:
        try:
            parsed = json.loads(applications)
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="`applications` must be valid JSON.")
        if not isinstance(parsed, list):
            raise HTTPException(status_code=422, detail="`applications` must be a JSON array.")
        apps_raw = [a for a in parsed if isinstance(a, dict)]

    by_name = {a["filename"]: a for a in apps_raw if a.get("filename")}

    # Read all uploads first (UploadFile is not safe to read concurrently).
    files = [(img.filename, _guess_mime(img.filename), await img.read()) for img in images]

    settings = get_settings()
    sem = asyncio.Semaphore(settings.batch_concurrency)

    async def run(idx: int, filename: Optional[str], mime: str, data: bytes) -> dict[str, Any]:
        expected = by_name.get(filename) or (apps_raw[idx] if idx < len(apps_raw) and not by_name else {})
        async with sem:
            try:
                res = await _verify_one(data, mime, expected)
            except OpenRouterError as exc:
                return {"filename": filename, "overall": "ERROR", "error": str(exc), "fields": []}
        res["filename"] = filename
        return res

    results = await asyncio.gather(
        *(run(i, fn, mime, data) for i, (fn, mime, data) in enumerate(files))
    )
    summary = {
        "total": len(results),
        "pass": sum(1 for r in results if r.get("overall") == "PASS"),
        "fail": sum(1 for r in results if r.get("overall") == "FAIL"),
        "error": sum(1 for r in results if r.get("overall") == "ERROR"),
    }
    return JSONResponse({"results": results, "summary": summary})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "index.html")


# Serve the rest of the static assets (css/js) under /static and at root paths.
if _FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=_FRONTEND_DIR), name="static")
