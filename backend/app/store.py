"""SQLite-backed store for the review queue.

A single small DB file on a persistent volume holds every submitted label, its AI
verdict, the OCR/alignment geometry, reviewer edits, and the final decision — the
audit trail a compliance review needs. Original images are written alongside it.

sqlite3 is synchronous; FastAPI runs our route handlers in a threadpool, and a
module-level lock serializes writes. Traffic for a review station is low, so this
is plenty and avoids pulling in an async DB dependency.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .config import get_settings

_JSON_COLS = {"expected", "extracted", "fields", "ocr", "alignment", "audit"}
_LIGHT_DROP = {"ocr", "alignment"}  # heavy blobs omitted from list views

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _data_dir() -> Path:
    d = get_settings().data_dir
    (d / "images").mkdir(parents=True, exist_ok=True)
    return d


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        db_path = _data_dir() / "ttb.db"
        _conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        # Multiple uvicorn workers each hold a connection; wait rather than error
        # if another worker is mid-write.
        _conn.execute("PRAGMA busy_timeout=5000")
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL,
            filename TEXT,
            mime TEXT,
            image_path TEXT,
            image_w INTEGER,
            image_h INTEGER,
            ai_overall TEXT,
            overall TEXT,
            reviewer TEXT,
            decided_at TEXT,
            decision_note TEXT,
            expected TEXT,
            extracted TEXT,
            fields TEXT,
            ocr TEXT,
            alignment TEXT,
            elapsed_ms INTEGER,
            edited INTEGER DEFAULT 0,
            audit TEXT
        )
    """)
    conn.commit()


def init_db() -> None:
    """Eagerly create the DB/schema at startup (so the volume is writable)."""
    with _lock:
        _connect()


def images_dir() -> Path:
    return _data_dir() / "images"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _row_to_dict(row: sqlite3.Row, light: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in row.keys():
        if light and key in _LIGHT_DROP:
            continue
        val = row[key]
        if key in _JSON_COLS and val is not None:
            try:
                val = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                val = None
        out[key] = val
    out["edited"] = bool(out.get("edited"))
    return out


def create_item(*, filename: str, mime: str, image_path: str, image_w: int, image_h: int,
                ai_overall: str, expected: dict, extracted: dict, fields: list,
                ocr: dict, alignment: dict, elapsed_ms: int) -> dict[str, Any]:
    item_id = uuid.uuid4().hex
    now = _now()
    audit = [{"at": now, "action": "submitted", "by": None,
              "detail": f"AI verdict: {ai_overall}"}]
    with _lock:
        conn = _connect()
        conn.execute(
            """INSERT INTO items (id, created_at, updated_at, status, filename, mime,
                 image_path, image_w, image_h, ai_overall, overall, reviewer, decided_at,
                 decision_note, expected, extracted, fields, ocr, alignment, elapsed_ms,
                 edited, audit)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item_id, now, now, "pending", filename, mime, image_path, image_w, image_h,
             ai_overall, ai_overall, None, None, None,
             json.dumps(expected), json.dumps(extracted), json.dumps(fields),
             json.dumps(ocr), json.dumps(alignment), elapsed_ms, 0, json.dumps(audit)),
        )
        conn.commit()
    return get_item(item_id)


def get_item(item_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_items(status: Optional[str] = None) -> list[dict[str, Any]]:
    """Lightweight rows (no OCR/alignment blobs) for queue/history lists."""
    with _lock:
        conn = _connect()
        if status:
            rows = conn.execute("SELECT * FROM items WHERE status=?", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM items").fetchall()
    return [_row_to_dict(r, light=True) for r in rows]


def update_item(item_id: str, **cols: Any) -> Optional[dict[str, Any]]:
    if not cols:
        return get_item(item_id)
    sets, vals = [], []
    for key, val in cols.items():
        sets.append(f"{key}=?")
        vals.append(json.dumps(val) if key in _JSON_COLS else val)
    sets.append("updated_at=?")
    vals.append(_now())
    vals.append(item_id)
    with _lock:
        conn = _connect()
        conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()
    return get_item(item_id)


def append_audit(item_id: str, action: str, by: Optional[str], detail: str = "") -> None:
    item = get_item(item_id)
    if not item:
        return
    audit = item.get("audit") or []
    audit.append({"at": _now(), "action": action, "by": by, "detail": detail})
    update_item(item_id, audit=audit)


def delete_item(item_id: str) -> bool:
    item = get_item(item_id)
    if not item:
        return False
    img = item.get("image_path")
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))
        conn.commit()
    if img:
        try:
            Path(img).unlink(missing_ok=True)
        except OSError:
            pass
    return True


def counts() -> dict[str, int]:
    with _lock:
        conn = _connect()
        rows = conn.execute("SELECT status, COUNT(*) c FROM items GROUP BY status").fetchall()
    out = {"pending": 0, "approved": 0, "declined": 0}
    for r in rows:
        out[r["status"]] = r["c"]
    return out
