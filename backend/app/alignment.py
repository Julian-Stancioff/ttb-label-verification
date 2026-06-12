"""Link extracted field *values* to OCR word *boxes*.

The vision model tells us what each field says (e.g. brand = "Old Tom Distillery");
Tesseract tells us where every word sits. This module finds, for each field, the
run of OCR words that best matches the field's value, so the UI can highlight the
exact region on the image when a reviewer focuses a field — and vice-versa.

Matching is deliberately fuzzy: tiny label print makes Tesseract merge/split words
("to the" -> "tothe"), so we score whole token-windows rather than demanding exact
word equality.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Optional

from .ocr import union_box

# Fields we try to ground on the image, in display order. Each maps to the key in
# the extraction payload that holds its verbatim text.
GROUNDED_FIELDS: list[tuple[str, str]] = [
    ("brand_name", "brand_name"),
    ("class_type", "class_type"),
    ("alcohol_content", "alcohol_content"),
    ("net_contents", "net_contents"),
    ("producer_name_address", "producer_name_address"),
    ("country_of_origin", "country_of_origin"),
    ("government_warning", "government_warning_text"),
]

_MIN_SCORE = 0.45  # below this we report "not located" rather than a bad box.
_CLUSTER_GAP = 3   # matched OCR words within this many positions belong together.


def _tokens(s: Optional[str]) -> list[str]:
    if not s:
        return []
    s = s.replace("’", "'").replace("‘", "'").lower()
    return re.findall(r"[a-z0-9]+", s)


def _best_window(field_tokens: list[str], ocr_tokens: list[str]) -> tuple[float, list[int]]:
    """Find the OCR words that belong to ``field_tokens``.

    Uses sequence matching to pick the OCR indices that actually align to the
    field's words (in reading order), then keeps the single densest contiguous
    cluster so a stray duplicate word elsewhere on the label can't balloon the
    box. Returns ``(coverage_score, ocr_indices)``.
    """
    n, k = len(ocr_tokens), len(field_tokens)
    if k == 0 or n == 0:
        return 0.0, []

    # OCR indices that align to some field token, in order.
    sm = SequenceMatcher(None, ocr_tokens, field_tokens, autojunk=False)
    matched = [blk.a + off for blk in sm.get_matching_blocks()
               for off in range(blk.size)]
    if not matched:
        return 0.0, []

    # Split into contiguous clusters (tolerating small OCR gaps), keep the richest.
    clusters: list[list[int]] = [[matched[0]]]
    for idx in matched[1:]:
        if idx - clusters[-1][-1] <= _CLUSTER_GAP:
            clusters[-1].append(idx)
        else:
            clusters.append([idx])
    best = max(clusters, key=len)

    # Coverage = how much of the field text this cluster accounts for.
    covered = {ocr_tokens[i] for i in best}
    score = sum(1 for t in field_tokens if t in covered) / k
    # Fill small interior gaps so the union box is solid, not dotted.
    full = list(range(best[0], best[-1] + 1))
    return score, full


def align_fields(extraction: dict[str, Any], ocr: dict[str, Any]) -> dict[str, Any]:
    """Return ``{field: {box, score, located, word_boxes}}`` for grounded fields.

    ``box`` is a normalized union rectangle (or None). ``word_boxes`` are the
    individual matched word rectangles (for crisp per-word highlighting).
    """
    words = ocr.get("words", [])
    ocr_tokens = [(_tokens(w["text"]) or [""])[0] for w in words]

    out: dict[str, Any] = {}
    for field, ext_key in GROUNDED_FIELDS:
        value = extraction.get(ext_key)
        ft = _tokens(value)
        if not ft or not words:
            out[field] = {"box": None, "score": 0.0, "located": False, "word_boxes": []}
            continue
        score, idx = _best_window(ft, ocr_tokens)
        if score < _MIN_SCORE or not idx:
            out[field] = {"box": None, "score": round(score, 3), "located": False, "word_boxes": []}
            continue
        matched = [words[i] for i in idx]
        word_boxes = [
            {"nx": w["nx"], "ny": w["ny"], "nw": w["nw"], "nh": w["nh"]} for w in matched
        ]
        out[field] = {
            "box": union_box(matched),
            "score": round(score, 3),
            "located": True,
            "word_boxes": word_boxes,
        }
    return out
