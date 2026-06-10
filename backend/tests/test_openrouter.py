"""Unit tests for the OpenRouter client + extraction parsing (HTTP fully mocked)."""
from __future__ import annotations

import json

import httpx
import pytest

import app.openrouter as orm
from app.config import get_settings
from app.extraction import parse_extraction_json
from app.openrouter import OpenRouterError, chat_vision_json, image_to_data_url


def test_image_to_data_url():
    url = image_to_data_url(b"hello", "image/png")
    assert url.startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_chat_vision_requires_api_key(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(OpenRouterError):
        await chat_vision_json(system_prompt="s", user_text="u", image_data_url="data:,x")
    get_settings.cache_clear()


def _patch_transport(monkeypatch, transport):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        orm.httpx, "AsyncClient",
        lambda *a, **k: real(*a, **{**k, "transport": transport}),
    )


@pytest.mark.asyncio
async def test_chat_vision_returns_content(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    payload = {"choices": [{"message": {"content": '{"brand_name": "ACME"}'}}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=payload)

    _patch_transport(monkeypatch, httpx.MockTransport(handler))
    content = await chat_vision_json(system_prompt="s", user_text="u", image_data_url="data:,x")
    assert json.loads(content)["brand_name"] == "ACME"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chat_vision_http_error(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _patch_transport(monkeypatch, httpx.MockTransport(lambda req: httpx.Response(500, text="boom")))
    with pytest.raises(OpenRouterError):
        await chat_vision_json(system_prompt="s", user_text="u", image_data_url="data:,x")
    get_settings.cache_clear()


# --- extraction JSON parsing ----------------------------------------------

def test_parse_extraction_plain_json():
    out = parse_extraction_json('{"brand_name": "ACME", "abv_percent": "45%"}')
    assert out["brand_name"] == "ACME"
    assert out["abv_percent"] == 45.0  # coerced from "45%"


def test_parse_extraction_fenced_json():
    out = parse_extraction_json('```json\n{"brand_name": "ACME"}\n```')
    assert out["brand_name"] == "ACME"


def test_parse_extraction_bad_json_raises():
    with pytest.raises(OpenRouterError):
        parse_extraction_json("not json at all")
