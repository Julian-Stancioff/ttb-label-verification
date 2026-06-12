"""Word-level OCR via Tesseract.

Produces pixel-accurate bounding boxes for *every* readable word on the label
("show everything"). Coordinates are returned both in pixels and normalized to
0..1 so the frontend can overlay them on the image at any display size.

This is intentionally separate from the vision extraction (`extraction.py`):
Tesseract gives trustworthy geometry, the vision model gives semantic fields,
and `alignment.py` links the two.
"""
from __future__ import annotations

import io
from typing import Any, Optional

from PIL import Image, ImageOps

try:
    import pytesseract
    from pytesseract import Output
    _HAVE_TESSERACT = True
except Exception:  # pragma: no cover - import guard
    pytesseract = None  # type: ignore
    Output = None  # type: ignore
    _HAVE_TESSERACT = False

# Tesseract confidence below this is treated as noise and dropped.
_MIN_CONF = 35.0
# Upscale small images so Tesseract has enough pixels to read crisp boxes.
_MIN_DIM_FOR_OCR = 1000


def _load_image(image_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes))
    # Respect EXIF orientation so boxes line up with what the reviewer sees.
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def ocr_words(image_bytes: bytes) -> dict[str, Any]:
    """Return ``{width, height, words: [...], available: bool}``.

    Each word: ``{text, conf, x, y, w, h, nx, ny, nw, nh, line}`` where x/y/w/h
    are pixels in the *original* image and n* are the same normalized to 0..1.
    ``line`` is a stable id for the OCR line the word belongs to (block/par/line).
    """
    img = _load_image(image_bytes)
    width, height = img.size

    if not _HAVE_TESSERACT:
        return {"width": width, "height": height, "words": [], "available": False}

    # Upscale small scans for better recognition, then map boxes back to original px.
    scale = 1.0
    ocr_img = img
    longest = max(width, height)
    if longest < _MIN_DIM_FOR_OCR:
        scale = _MIN_DIM_FOR_OCR / longest
        ocr_img = img.resize((round(width * scale), round(height * scale)))

    try:
        data = pytesseract.image_to_data(ocr_img, output_type=Output.DICT)
    except Exception:
        return {"width": width, "height": height, "words": [], "available": False}

    words: list[dict[str, Any]] = []
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1.0
        if conf < _MIN_CONF:
            continue
        # Map back to original-image pixels.
        x = data["left"][i] / scale
        y = data["top"][i] / scale
        w = data["width"][i] / scale
        h = data["height"][i] / scale
        line_id = f'{data["block_num"][i]}_{data["par_num"][i]}_{data["line_num"][i]}'
        words.append({
            "text": text,
            "conf": round(conf, 1),
            "x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1),
            "nx": round(x / width, 5), "ny": round(y / height, 5),
            "nw": round(w / width, 5), "nh": round(h / height, 5),
            "line": line_id,
        })

    return {"width": width, "height": height, "words": words, "available": True}


def union_box(words: list[dict[str, Any]]) -> Optional[dict[str, float]]:
    """Tight normalized bounding box around a set of OCR words (or None)."""
    if not words:
        return None
    x0 = min(w["nx"] for w in words)
    y0 = min(w["ny"] for w in words)
    x1 = max(w["nx"] + w["nw"] for w in words)
    y1 = max(w["ny"] + w["nh"] for w in words)
    return {"nx": round(x0, 5), "ny": round(y0, 5),
            "nw": round(x1 - x0, 5), "nh": round(y1 - y0, 5)}
