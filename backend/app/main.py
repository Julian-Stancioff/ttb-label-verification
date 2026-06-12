"""FastAPI service: label verification API + review queue + static frontend."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import store
from .config import get_settings
from .extraction import extract_label_fields
from .openrouter import OpenRouterError
from .service import rematch, run_pipeline
from .verification import verify

@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.init_db()
    yield


app = FastAPI(title="TTB Label Verification", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

_EXT_BY_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


def _guess_mime(filename: Optional[str]) -> str:
    name = (filename or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith(".gif"):
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


# ===================================================================
# Legacy stateless endpoints (kept for compatibility + the test suite)
# ===================================================================

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


# ===================================================================
# Review-queue API (persistent)
# ===================================================================

def _save_image(image_bytes: bytes, mime: str) -> str:
    ext = _EXT_BY_MIME.get(mime, ".jpg")
    path = store.images_dir() / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(image_bytes)
    return str(path)


async def _intake_one(image_bytes: bytes, filename: str, mime: str,
                      expected: dict[str, Any]) -> dict[str, Any]:
    """Run the pipeline and persist one queue item (degrades to an ERROR item)."""
    image_path = _save_image(image_bytes, mime)
    try:
        pipe = await run_pipeline(image_bytes, mime, expected)
        ai_overall = pipe["overall"]
        extracted, fields = pipe["extracted"], pipe["fields"]
        ocr, alignment = pipe["ocr"], pipe["alignment"]
        image_w, image_h = pipe["image_w"], pipe["image_h"]
        elapsed_ms = pipe["elapsed_ms"]
    except OpenRouterError as exc:
        # Keep it in the queue so a human can Redo — never silently drop a submission.
        ai_overall = "ERROR"
        extracted, fields = {"error": str(exc)}, []
        ocr, alignment = {"words": [], "width": 0, "height": 0}, {}
        image_w = image_h = 0
        elapsed_ms = 0
    return store.create_item(
        filename=filename or "label", mime=mime, image_path=image_path,
        image_w=image_w or 0, image_h=image_h or 0, ai_overall=ai_overall,
        expected=expected, extracted=extracted, fields=fields, ocr=ocr,
        alignment=alignment, elapsed_ms=elapsed_ms,
    )


@app.post("/api/items")
async def create_item(
    image: UploadFile = File(...),
    application: Optional[str] = Form(None),
) -> JSONResponse:
    """Intake one label: run the AI and drop it in the review queue."""
    expected = _parse_application(application)
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="Uploaded image is empty.")
    item = await _intake_one(image_bytes, image.filename, _guess_mime(image.filename), expected)
    return JSONResponse(item, status_code=201)


@app.post("/api/items/batch")
async def create_items_batch(
    images: list[UploadFile] = File(...),
    applications: Optional[str] = Form(None),
) -> JSONResponse:
    """Intake many labels; each becomes its own queue item."""
    apps_raw: list[dict[str, Any]] = []
    if applications:
        try:
            parsed = json.loads(applications)
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="`applications` must be valid JSON.")
        if isinstance(parsed, list):
            apps_raw = [a for a in parsed if isinstance(a, dict)]
    by_name = {a["filename"]: a for a in apps_raw if a.get("filename")}

    files = [(img.filename, _guess_mime(img.filename), await img.read()) for img in images]
    settings = get_settings()
    sem = asyncio.Semaphore(settings.batch_concurrency)

    async def run(idx: int, filename: str, mime: str, data: bytes) -> dict[str, Any]:
        expected = by_name.get(filename) or (apps_raw[idx] if idx < len(apps_raw) and not by_name else {})
        async with sem:
            return await _intake_one(data, filename, mime, expected)

    created = await asyncio.gather(
        *(run(i, fn, mime, data) for i, (fn, mime, data) in enumerate(files))
    )
    return JSONResponse({"created": len(created), "items": created}, status_code=201)


def _attention_rank(item: dict[str, Any]) -> int:
    """Lower sorts first: errors, then fails, then anything unresolved, then passes."""
    overall = (item.get("overall") or "").upper()
    if overall == "ERROR":
        return 0
    if overall == "FAIL":
        return 1
    if overall == "PASS":
        return 3
    return 2


@app.get("/api/items")
async def list_items(status: str = "pending") -> JSONResponse:
    """List queue (status=pending) or history (status=decided/approved/declined)."""
    if status == "decided":
        items = store.list_items("approved") + store.list_items("declined")
    elif status == "all":
        items = store.list_items()
    else:
        items = store.list_items(status)

    if status in ("pending", "all"):
        # Exception-first, then newest-first within each rank (stable sort).
        items.sort(key=lambda it: it.get("created_at") or "", reverse=True)
        items.sort(key=_attention_rank)
    else:
        items.sort(key=lambda it: it.get("decided_at") or it.get("created_at") or "", reverse=True)
    return JSONResponse({"items": items, "counts": store.counts()})


@app.get("/api/stats")
async def stats() -> JSONResponse:
    return JSONResponse(store.counts())


@app.get("/api/items/{item_id}")
async def get_item(item_id: str) -> JSONResponse:
    item = store.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    return JSONResponse(item)


@app.get("/api/items/{item_id}/image")
async def get_item_image(item_id: str) -> FileResponse:
    item = store.get_item(item_id)
    if not item or not item.get("image_path"):
        raise HTTPException(status_code=404, detail="Image not found.")
    path = Path(item["image_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file missing.")
    return FileResponse(path, media_type=item.get("mime") or "image/jpeg")


class EditBody(BaseModel):
    expected: Optional[dict[str, Any]] = None
    extracted: Optional[dict[str, Any]] = None
    reviewer: Optional[str] = None


@app.post("/api/items/{item_id}/edit")
async def edit_item(item_id: str, body: EditBody) -> JSONResponse:
    """Apply reviewer corrections to either side and re-run the deterministic match."""
    item = store.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail="Only pending items can be edited.")

    expected = body.expected if body.expected is not None else (item.get("expected") or {})
    extracted = body.extracted if body.extracted is not None else (item.get("extracted") or {})
    res = rematch(expected, extracted, item.get("ocr") or {})

    store.update_item(item_id, expected=expected, extracted=extracted,
                      fields=res["fields"], overall=res["overall"],
                      alignment=res["alignment"], edited=1)
    store.append_audit(item_id, "edited", body.reviewer,
                       f"Reviewer corrected values; verdict now {res['overall']}.")
    return JSONResponse(store.get_item(item_id))


@app.post("/api/items/{item_id}/redo")
async def redo_item(
    item_id: str,
    image: Optional[UploadFile] = File(None),
    reviewer: Optional[str] = Form(None),
) -> JSONResponse:
    """Re-run the AI pipeline, optionally against a replacement image."""
    item = store.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail="Only pending items can be redone.")

    if image is not None:
        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(status_code=422, detail="Replacement image is empty.")
        mime = _guess_mime(image.filename)
        new_path = _save_image(image_bytes, mime)
        old_path = item.get("image_path")
        if old_path and old_path != new_path:
            Path(old_path).unlink(missing_ok=True)
        store.update_item(item_id, image_path=new_path, mime=mime, filename=image.filename or item["filename"])
        swapped = True
    else:
        mime = item.get("mime") or "image/jpeg"
        image_bytes = Path(item["image_path"]).read_bytes()
        swapped = False

    expected = item.get("expected") or {}
    try:
        pipe = await run_pipeline(image_bytes, mime, expected)
    except OpenRouterError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    store.update_item(item_id, extracted=pipe["extracted"], fields=pipe["fields"],
                      overall=pipe["overall"], ai_overall=pipe["overall"],
                      ocr=pipe["ocr"], alignment=pipe["alignment"],
                      image_w=pipe["image_w"] or 0, image_h=pipe["image_h"] or 0,
                      elapsed_ms=pipe["elapsed_ms"], edited=0)
    detail = f"Re-ran AI{' on replacement image' if swapped else ''}; verdict {pipe['overall']}."
    store.append_audit(item_id, "redo", reviewer, detail)
    return JSONResponse(store.get_item(item_id))


class DecideBody(BaseModel):
    decision: str  # "approve" | "decline"
    reviewer: Optional[str] = None
    note: Optional[str] = None


@app.post("/api/items/{item_id}/decide")
async def decide_item(item_id: str, body: DecideBody) -> JSONResponse:
    item = store.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    decision = body.decision.lower()
    if decision not in ("approve", "decline"):
        raise HTTPException(status_code=422, detail="decision must be 'approve' or 'decline'.")
    status = "approved" if decision == "approve" else "declined"
    store.update_item(item_id, status=status, reviewer=body.reviewer,
                      decided_at=store._now(), decision_note=body.note)
    store.append_audit(item_id, status, body.reviewer, body.note or "")
    return JSONResponse(store.get_item(item_id))


class BulkApproveBody(BaseModel):
    ids: list[str]
    reviewer: Optional[str] = None


@app.post("/api/items/bulk-approve")
async def bulk_approve(body: BulkApproveBody) -> JSONResponse:
    done = 0
    for item_id in body.ids:
        item = store.get_item(item_id)
        if not item or item["status"] != "pending":
            continue
        store.update_item(item_id, status="approved", reviewer=body.reviewer,
                          decided_at=store._now(), decision_note="Bulk approved.")
        store.append_audit(item_id, "approved", body.reviewer, "Bulk approved.")
        done += 1
    return JSONResponse({"approved": done})


@app.delete("/api/items/{item_id}")
async def delete_item(item_id: str) -> JSONResponse:
    if not store.delete_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found.")
    return JSONResponse({"deleted": item_id})


# ===================================================================
# Frontend
# ===================================================================

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "index.html")


if _FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=_FRONTEND_DIR), name="static")
