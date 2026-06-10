"""Thin async client for the OpenRouter chat/completions API (OpenAI-compatible)."""
from __future__ import annotations

import base64
from typing import Any

import httpx

from .config import get_settings


class OpenRouterError(RuntimeError):
    """Raised when the model call fails or returns an unusable response."""


def image_to_data_url(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


async def chat_vision_json(
    *,
    system_prompt: str,
    user_text: str,
    image_data_url: str,
    max_tokens: int = 1500,
) -> str:
    """Send one text+image message and return the assistant's text content.

    Requests a JSON object response. Raises OpenRouterError on any failure so
    callers can surface a clean message instead of a stack trace.
    """
    settings = get_settings()
    if not settings.configured:
        raise OpenRouterError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "max_tokens": max_tokens,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        # Optional attribution headers recommended by OpenRouter.
        "HTTP-Referer": "https://github.com/Julian-Stancioff/ttb-label-verification",
        "X-Title": "TTB Label Verification",
    }

    url = f"{settings.openrouter_base_url}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise OpenRouterError("The model took too long to respond. Please retry.") from exc
    except httpx.HTTPError as exc:
        raise OpenRouterError(f"Could not reach the model service: {exc}") from exc

    if resp.status_code != 200:
        raise OpenRouterError(
            f"Model service returned {resp.status_code}: {resp.text[:300]}"
        )

    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise OpenRouterError("Model returned an unexpected response shape.") from exc
