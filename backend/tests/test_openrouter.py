"""Unit tests for the OpenRouter client.

The HTTP call is mocked via httpx.MockTransport so no network is touched.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.openrouter import (
    OpenRouterClient,
    OpenRouterError,
    _extract_assistant_text,
)

PNG_DATA_URL = "data:image/png;base64,iVBORw0KGgo="


def _settings(**over: object) -> Settings:
    base = dict(
        openrouter_api_key="test-key",
        openrouter_base_url="https://example.test/api/v1",
        llm_model="anthropic/claude-sonnet-4.5",
    )
    base.update(over)
    return Settings(**base)


def _client_with_handler(handler, **settings_over) -> OpenRouterClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return OpenRouterClient(_settings(**settings_over), client=http)


@pytest.mark.asyncio
async def test_send_text_and_image_returns_assistant_text():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": '{"brand_name":"X"}'}}
                ]
            },
        )

    client = _client_with_handler(handler)
    result = await client.send_text_and_image(
        "extract fields",
        PNG_DATA_URL,
        response_format={"type": "json_object"},
    )

    assert result == '{"brand_name":"X"}'
    assert captured["url"] == "https://example.test/api/v1/chat/completions"
    assert captured["auth"] == "Bearer test-key"

    body = captured["body"]
    assert body["model"] == "anthropic/claude-sonnet-4.5"
    assert body["response_format"] == {"type": "json_object"}
    # The user message must carry both the text and the image data URL.
    content = body["messages"][0]["content"]
    types = {part["type"] for part in content}
    assert types == {"text", "image_url"}
    image_part = next(p for p in content if p["type"] == "image_url")
    assert image_part["image_url"]["url"] == PNG_DATA_URL


@pytest.mark.asyncio
async def test_chat_uses_model_override():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    client = _client_with_handler(handler)
    await client.send_text_and_image("hi", PNG_DATA_URL, model="other/model")
    assert captured["body"]["model"] == "other/model"


@pytest.mark.asyncio
async def test_missing_api_key_raises():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not be called")

    client = _client_with_handler(handler, openrouter_api_key="")
    with pytest.raises(OpenRouterError, match="API_KEY"):
        await client.send_text_and_image("hi", PNG_DATA_URL)


@pytest.mark.asyncio
async def test_http_error_status_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = _client_with_handler(handler)
    with pytest.raises(OpenRouterError, match="401"):
        await client.send_text_and_image("hi", PNG_DATA_URL)


@pytest.mark.asyncio
async def test_non_json_body_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    client = _client_with_handler(handler)
    with pytest.raises(OpenRouterError, match="non-JSON"):
        await client.chat([{"role": "user", "content": "hi"}])


def test_extract_assistant_text_from_list_content():
    body = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": "hello "},
                        {"type": "text", "text": "world"},
                    ]
                }
            }
        ]
    }
    assert _extract_assistant_text(body) == "hello world"


def test_extract_assistant_text_bad_shape_raises():
    with pytest.raises(OpenRouterError):
        _extract_assistant_text({"nope": True})
