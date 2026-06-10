"""Unit tests for the deterministic verification logic."""
from app.verification import (
    CANONICAL_WARNING,
    check_abv,
    check_brand,
    check_government_warning,
    parse_abv,
    verify,
)


# --- brand judgment (Dave's STONE'S THROW rule) ---------------------------

def test_brand_exact_match():
    assert check_brand("OLD TOM DISTILLERY", "OLD TOM DISTILLERY").status == "match"


def test_brand_case_and_punctuation_tolerant():
    r = check_brand("STONE'S THROW", "Stone's Throw")
    assert r.status == "match"
    assert "minor case" in r.note.lower()


def test_brand_curly_apostrophe_match():
    assert check_brand("Stone's Throw", "Stone’s Throw").status == "match"


def test_brand_ampersand_equals_and():
    assert check_brand("Smith & Sons", "Smith and Sons").status == "match"


def test_brand_genuine_mismatch():
    assert check_brand("OLD TOM", "NEW TOM").status == "mismatch"


def test_brand_missing():
    assert check_brand("OLD TOM", None).status == "missing"


# --- ABV ------------------------------------------------------------------

def test_parse_abv_variants():
    assert parse_abv("45% Alc./Vol. (90 Proof)") == 45.0
    assert parse_abv("45") == 45.0
    assert parse_abv(40) == 40.0
    assert parse_abv(None) is None


def test_abv_match():
    assert check_abv("45% Alc./Vol.", 45.0, "45% Alc./Vol.").status == "match"


def test_abv_mismatch():
    r = check_abv("45%", 40.0, "40% Alc./Vol.")
    assert r.status == "mismatch"
    assert "40" in r.note and "45" in r.note


# --- government warning (Jenny's strict rule) -----------------------------

def test_warning_exact_match():
    r = check_government_warning(CANONICAL_WARNING, True)
    assert r.status == "match"


def test_warning_tolerates_linebreaks_and_spacing():
    spaced = CANONICAL_WARNING.replace(" ", "\n  ", 3)
    assert check_government_warning(spaced, True).status == "match"


def test_warning_title_case_header_rejected():
    cheat = CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")
    r = check_government_warning(cheat, False)
    assert r.status == "mismatch"
    assert "all-caps" in r.note.lower()


def test_warning_paraphrase_rejected():
    cheat = CANONICAL_WARNING.replace("birth defects", "birth problems")
    r = check_government_warning(cheat, True)
    assert r.status == "mismatch"
    assert "wording differs" in r.note.lower()


def test_warning_missing_rejected():
    r = check_government_warning(None, False)
    assert r.status == "missing"


# --- end to end -----------------------------------------------------------

def test_verify_overall_pass():
    expected = {"brand_name": "OLD TOM DISTILLERY", "alcohol_content": "45% Alc./Vol."}
    extracted = {
        "brand_name": "Old Tom Distillery",
        "abv_percent": 45.0,
        "alcohol_content": "45% Alc./Vol. (90 Proof)",
        "government_warning_text": CANONICAL_WARNING,
        "government_warning_is_allcaps_header": True,
    }
    out = verify(expected, extracted)
    assert out["overall"] == "PASS"


def test_verify_overall_fail_on_warning():
    expected = {"brand_name": "OLD TOM DISTILLERY", "alcohol_content": "45% Alc./Vol."}
    extracted = {
        "brand_name": "Old Tom Distillery",
        "abv_percent": 45.0,
        "alcohol_content": "45% Alc./Vol.",
        "government_warning_text": CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:"),
        "government_warning_is_allcaps_header": False,
    }
    out = verify(expected, extracted)
    assert out["overall"] == "FAIL"
