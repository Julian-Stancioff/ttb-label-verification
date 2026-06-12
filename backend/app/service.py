"""Orchestrates one label through the full pipeline.

extraction (vision) + OCR (Tesseract) + deterministic match + field→box alignment.
Shared by intake and by the reviewer's "Redo". Kept apart from the HTTP layer so it
can be unit-tested and reused.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .alignment import align_fields
from .extraction import extract_label_fields
from .ocr import ocr_words
from .verification import verify


async def run_pipeline(image_bytes: bytes, mime: str, expected: dict[str, Any]) -> dict[str, Any]:
    """Return everything needed to persist a queue item (no DB I/O here).

    Vision extraction (network) and OCR (CPU) run concurrently; OCR is pushed to a
    thread so it doesn't block the event loop.
    """
    start = time.perf_counter()
    extracted, ocr = await asyncio.gather(
        extract_label_fields(image_bytes, mime),
        asyncio.to_thread(ocr_words, image_bytes),
    )
    result = verify(expected, extracted)
    alignment = align_fields(extracted, ocr)
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    return {
        "extracted": extracted,
        "fields": result["fields"],
        "overall": result["overall"],
        "warning_detail": result.get("warning_detail"),
        "ocr": ocr,
        "alignment": alignment,
        "image_w": ocr.get("width"),
        "image_h": ocr.get("height"),
        "elapsed_ms": elapsed_ms,
    }


def rematch(expected: dict[str, Any], extracted: dict[str, Any], ocr: dict[str, Any]) -> dict[str, Any]:
    """Re-run the deterministic match + alignment after a reviewer edit.

    No AI calls — just the pure verification logic over the (possibly corrected)
    expected/extracted values, plus fresh box alignment for the new text.
    """
    result = verify(expected, extracted)
    return {
        "fields": result["fields"],
        "overall": result["overall"],
        "warning_detail": result.get("warning_detail"),
        "alignment": align_fields(extracted, ocr),
    }
