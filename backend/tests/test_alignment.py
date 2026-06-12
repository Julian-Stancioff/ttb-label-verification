"""Tests for field→OCR-box alignment (pure; no Tesseract needed)."""
from app.alignment import align_fields


def _word(text, x, y, w=0.05, h=0.02):
    return {"text": text, "conf": 90, "x": x, "y": y, "w": w, "h": h,
            "nx": x, "ny": y, "nw": w, "nh": h, "line": "1"}


def _ocr(words):
    return {"width": 1000, "height": 1000, "words": words, "available": True}


def test_locates_brand_and_warning():
    words = [
        _word("OLD", 0.40, 0.10), _word("TOM", 0.46, 0.10), _word("DISTILLERY", 0.52, 0.10),
        _word("Kentucky", 0.40, 0.20), _word("Bourbon", 0.50, 0.20),
        # warning words at the bottom
        _word("GOVERNMENT", 0.10, 0.80), _word("WARNING", 0.22, 0.80),
        _word("According", 0.10, 0.83), _word("Surgeon", 0.25, 0.83),
        _word("General", 0.35, 0.83), _word("problems", 0.10, 0.90),
    ]
    extraction = {
        "brand_name": "Old Tom Distillery",
        "government_warning_text": "GOVERNMENT WARNING According to the Surgeon General problems",
    }
    res = align_fields(extraction, _ocr(words))

    assert res["brand_name"]["located"] is True
    assert res["brand_name"]["box"] is not None
    # brand sits near the top
    assert res["brand_name"]["box"]["ny"] < 0.2

    assert res["government_warning"]["located"] is True
    # warning box should sit low on the label, not engulf the brand at the top
    assert res["government_warning"]["box"]["ny"] >= 0.75


def test_absent_field_not_located():
    words = [_word("Something", 0.4, 0.1)]
    extraction = {"brand_name": "Totally Different Name", "country_of_origin": None}
    res = align_fields(extraction, _ocr(words))
    assert res["brand_name"]["located"] is False
    assert res["country_of_origin"]["located"] is False


def test_no_ocr_words_is_safe():
    res = align_fields({"brand_name": "Anything"}, _ocr([]))
    assert res["brand_name"]["located"] is False
    assert res["brand_name"]["box"] is None
