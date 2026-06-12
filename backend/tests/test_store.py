"""Tests for the SQLite review-queue store (uses a temp data dir)."""
import pytest

from app import config, store


@pytest.fixture()
def fresh_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    store._conn = None  # force a new connection against the temp DB
    store.init_db()
    yield store
    store._conn = None
    config.get_settings.cache_clear()


def _make(s, **over):
    base = dict(
        filename="x.png", mime="image/png", image_path=str("/tmp/x.png"),
        image_w=100, image_h=100, ai_overall="PASS", expected={"brand_name": "A"},
        extracted={"brand_name": "A"}, fields=[{"field": "brand_name", "status": "match"}],
        ocr={"words": []}, alignment={}, elapsed_ms=1234,
    )
    base.update(over)
    return s.create_item(**base)


def test_create_and_get(fresh_store):
    item = _make(fresh_store)
    assert item["status"] == "pending"
    assert item["ai_overall"] == "PASS"
    assert item["overall"] == "PASS"
    assert item["expected"] == {"brand_name": "A"}
    assert len(item["audit"]) == 1 and item["audit"][0]["action"] == "submitted"
    assert fresh_store.get_item(item["id"])["id"] == item["id"]


def test_list_is_light(fresh_store):
    _make(fresh_store)
    rows = fresh_store.list_items("pending")
    assert len(rows) == 1
    # heavy blobs are dropped from list views
    assert "ocr" not in rows[0] and "alignment" not in rows[0]
    # but the verdict + fields needed for the row are present
    assert "fields" in rows[0] and rows[0]["overall"] == "PASS"


def test_update_and_audit(fresh_store):
    item = _make(fresh_store, ai_overall="FAIL")
    fresh_store.update_item(item["id"], overall="PASS", edited=1)
    fresh_store.append_audit(item["id"], "edited", "Reviewer", "fixed it")
    got = fresh_store.get_item(item["id"])
    assert got["overall"] == "PASS" and got["edited"] is True
    assert got["audit"][-1]["action"] == "edited" and got["audit"][-1]["by"] == "Reviewer"


def test_decide_moves_to_history_and_counts(fresh_store):
    a, b = _make(fresh_store), _make(fresh_store)
    fresh_store.update_item(a["id"], status="approved")
    assert fresh_store.counts() == {"pending": 1, "approved": 1, "declined": 0}
    assert {i["id"] for i in fresh_store.list_items("approved")} == {a["id"]}
    assert {i["id"] for i in fresh_store.list_items("pending")} == {b["id"]}


def test_delete(fresh_store):
    item = _make(fresh_store)
    assert fresh_store.delete_item(item["id"]) is True
    assert fresh_store.get_item(item["id"]) is None
    assert fresh_store.delete_item("nope") is False
