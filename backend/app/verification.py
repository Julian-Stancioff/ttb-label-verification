"""Deterministic verification of extracted label fields against application data.

Pure functions only (no I/O) so they are fast and unit-testable. See docs/SPEC.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Optional

# Canonical Government Warning per 27 CFR 16.21.
CANONICAL_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)

MATCH = "match"
MISMATCH = "mismatch"
MISSING = "missing"
NOT_CHECKED = "not_checked"


@dataclass
class FieldResult:
    field: str
    expected: Optional[str]
    found: Optional[str]
    status: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- normalization helpers -------------------------------------------------

def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def normalize_text(s: Optional[str]) -> str:
    """Case/punctuation-tolerant normalization for judgment-based fields (Dave's rule)."""
    if not s:
        return ""
    s = s.strip().lower()
    s = s.replace("’", "'").replace("‘", "'")  # curly -> straight apostrophes
    s = s.replace("&", " and ")
    s = _collapse_ws(s)
    s = re.sub(r"[^\w\s']", "", s)  # drop punctuation except apostrophes
    return _collapse_ws(s)


def _normalize_warning_words(s: str) -> list[str]:
    """Lowercased word/number tokens of a warning, ignoring punctuation & spacing."""
    s = s.replace("’", "'").replace("‘", "'")
    return re.findall(r"[a-z0-9]+", s.lower())


def parse_abv(value: Any) -> Optional[float]:
    """Pull a numeric ABV percentage out of a string or number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?", str(value))
    return float(m.group(1)) if m else None


# --- individual field checks ----------------------------------------------

def check_brand(expected: Optional[str], found: Optional[str]) -> FieldResult:
    if not expected:
        return FieldResult("brand_name", expected, found, NOT_CHECKED,
                           "No brand name in application.")
    if not found:
        return FieldResult("brand_name", expected, found, MISSING,
                           "Brand name not found on the label.")
    if normalize_text(expected) == normalize_text(found):
        note = ""
        if expected.strip() != found.strip():
            note = "Matches (minor case/punctuation difference, treated as equal)."
        return FieldResult("brand_name", expected, found, MATCH, note)
    return FieldResult("brand_name", expected, found, MISMATCH,
                       "Brand name on label differs from the application.")


def check_abv(expected: Optional[str], found_value: Any, found_display: Optional[str]) -> FieldResult:
    found_disp = found_display if found_display is not None else (
        str(found_value) if found_value is not None else None
    )
    if expected is None or str(expected).strip() == "":
        return FieldResult("alcohol_content", expected, found_disp, NOT_CHECKED,
                           "No alcohol content in application.")
    exp = parse_abv(expected)
    got = parse_abv(found_value if found_value is not None else found_display)
    if got is None:
        return FieldResult("alcohol_content", expected, found_disp, MISSING,
                           "Alcohol content not found on the label.")
    if exp is not None and abs(exp - got) < 1e-9:
        return FieldResult("alcohol_content", expected, found_disp, MATCH, "")
    return FieldResult("alcohol_content", expected, found_disp, MISMATCH,
                       f"Label shows {got}% but application says {exp}%.")


def check_government_warning(found_text: Optional[str], is_allcaps_header: Any) -> FieldResult:
    """The strict one (Jenny). PASS requires presence + all-caps header + word-for-word body."""
    if not found_text or not found_text.strip():
        return FieldResult("government_warning", CANONICAL_WARNING, found_text, MISSING,
                           "No government warning found on the label. This is mandatory.")

    found = found_text.strip()
    problems: list[str] = []

    # 1. Header must read "GOVERNMENT WARNING:" in all caps (tolerate line wraps in the header).
    header_uppercase_present = bool(re.search(r"GOVERNMENT\s+WARNING\s*:", found))
    model_says_allcaps = bool(is_allcaps_header)
    if not (header_uppercase_present and model_says_allcaps):
        problems.append(
            'the "GOVERNMENT WARNING:" header is not in all-caps as required'
        )

    # 2. Body must match the statutory text word-for-word (case-insensitive on letters).
    canon_words = _normalize_warning_words(CANONICAL_WARNING)
    found_words = _normalize_warning_words(found)
    if found_words != canon_words:
        # Find the first divergence to give a useful, human note.
        idx = next(
            (i for i in range(min(len(canon_words), len(found_words)))
             if canon_words[i] != found_words[i]),
            min(len(canon_words), len(found_words)),
        )
        if idx < len(canon_words):
            ctx = " ".join(canon_words[max(0, idx - 3):idx + 1])
            problems.append(f'wording differs from the required text near "...{ctx}"')
        elif len(found_words) > len(canon_words):
            problems.append("the warning contains extra text beyond the required statement")
        else:
            problems.append("the warning is missing required text")

    if problems:
        return FieldResult("government_warning", CANONICAL_WARNING, found, MISMATCH,
                           "Warning rejected: " + "; ".join(problems) + ".")
    return FieldResult("government_warning", CANONICAL_WARNING, found, MATCH,
                       "Exact match to the required statutory warning.")


def check_simple_text(field: str, expected: Optional[str], found: Optional[str]) -> FieldResult:
    if not expected:
        return FieldResult(field, expected, found, NOT_CHECKED, "Not provided in application.")
    if not found:
        return FieldResult(field, expected, found, MISSING, f"{field} not found on the label.")
    if normalize_text(expected) == normalize_text(found):
        return FieldResult(field, expected, found, MATCH, "")
    return FieldResult(field, expected, found, MISMATCH,
                       f"{field} on label differs from the application.")


# --- top-level orchestration ----------------------------------------------

# Application keys checked with the generic case-insensitive text comparison.
_SIMPLE_FIELDS = [
    ("class_type", "class_type"),
    ("net_contents", "net_contents"),
    ("producer_name_address", "producer_name_address"),
    ("country_of_origin", "country_of_origin"),
]


def verify(expected: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    """Compare expected application fields against extracted label fields.

    Returns {overall, fields[], warning_detail}. `overall` is "PASS" iff the
    government warning passes AND every *provided* expected field matches.
    """
    results: list[FieldResult] = []

    results.append(check_brand(expected.get("brand_name"), extracted.get("brand_name")))
    results.append(check_abv(
        expected.get("alcohol_content") or expected.get("abv_percent"),
        extracted.get("abv_percent"),
        extracted.get("alcohol_content"),
    ))
    warning = check_government_warning(
        extracted.get("government_warning_text"),
        extracted.get("government_warning_is_allcaps_header"),
    )
    results.append(warning)

    for exp_key, ext_key in _SIMPLE_FIELDS:
        if expected.get(exp_key):
            results.append(check_simple_text(exp_key, expected.get(exp_key), extracted.get(ext_key)))

    # Overall: warning must pass; any checked field that is a mismatch/missing fails it.
    blocking = [r for r in results if r.status in (MISMATCH, MISSING)]
    overall = "PASS" if not blocking else "FAIL"

    return {
        "overall": overall,
        "fields": [r.to_dict() for r in results],
        "warning_detail": warning.to_dict(),
    }
