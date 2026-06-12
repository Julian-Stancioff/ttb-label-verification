"""Integration tests for the review-queue API (pipeline mocked, no network)."""
import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import config, store
    config.get_settings.cache_clear()
    store._conn = None
    import app.main as main

    async def fake_pipeline(image_bytes, mime, expected):
        # Pretend the AI read a label whose brand mismatches the application.
        extracted = {"brand_name": "LABEL BRAND", "alcohol_content": "40% Alc./Vol.",
                     "abv_percent": 40.0, "government_warning_text": None,
                     "government_warning_is_allcaps_header": False}
        from app.verification import verify
        res = verify(expected, extracted)
        return {"extracted": extracted, "fields": res["fields"], "overall": res["overall"],
                "warning_detail": res.get("warning_detail"),
                "ocr": {"width": 10, "height": 10, "words": []}, "alignment": {},
                "image_w": 10, "image_h": 10, "elapsed_ms": 5}

    monkeypatch.setattr(main, "run_pipeline", fake_pipeline)
    with TestClient(main.app) as c:
        yield c
    store._conn = None
    config.get_settings.cache_clear()


def _png():
    return ("l.png", io.BytesIO(b"\x89PNG\r\n\x1a\nfake"), "image/png")


def test_intake_creates_pending_item(client):
    r = client.post("/api/items", files={"image": _png()},
                    data={"application": '{"brand_name": "REAL BRAND"}'})
    assert r.status_code == 201
    item = r.json()
    assert item["status"] == "pending"
    assert item["overall"] == "FAIL"  # brand mismatch
    q = client.get("/api/items?status=pending").json()
    assert q["counts"]["pending"] == 1
    assert len(q["items"]) == 1


def test_edit_rematches_and_can_flip_verdict(client):
    item = client.post("/api/items", files={"image": _png()},
                       data={"application": '{"brand_name": "REAL BRAND"}'}).json()
    # Correct the application to match what the label says → should flip to PASS-ish.
    r = client.post(f"/api/items/{item['id']}/edit",
                    json={"expected": {"brand_name": "LABEL BRAND"}, "reviewer": "Jane"})
    assert r.status_code == 200
    edited = r.json()
    assert edited["edited"] is True
    brand = next(f for f in edited["fields"] if f["field"] == "brand_name")
    assert brand["status"] == "match"
    assert edited["audit"][-1]["action"] == "edited"


def test_decide_approve_moves_to_history(client):
    item = client.post("/api/items", files={"image": _png()}, data={"application": "{}"}).json()
    r = client.post(f"/api/items/{item['id']}/decide",
                    json={"decision": "approve", "reviewer": "Jane", "note": "ok"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    decided = client.get("/api/items?status=decided").json()
    assert [i["id"] for i in decided["items"]] == [item["id"]]
    assert client.get("/api/items?status=pending").json()["counts"]["approved"] == 1


def test_bulk_approve(client):
    ids = [client.post("/api/items", files={"image": _png()}, data={"application": "{}"}).json()["id"]
           for _ in range(3)]
    r = client.post("/api/items/bulk-approve", json={"ids": ids, "reviewer": "Jane"})
    assert r.json()["approved"] == 3
    assert client.get("/api/stats").json()["approved"] == 3


def test_decide_rejects_bad_decision(client):
    item = client.post("/api/items", files={"image": _png()}, data={"application": "{}"}).json()
    r = client.post(f"/api/items/{item['id']}/decide", json={"decision": "maybe"})
    assert r.status_code == 422


def test_missing_item_404(client):
    assert client.get("/api/items/nope").status_code == 404
