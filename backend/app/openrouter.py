"""Async OpenRouter client.

Thin wrapper over the OpenRouter Chat Completions API (OpenAI-compatible).
Other modules (extraction, verification) build on top of this — keep it
focused on transport and message shaping, no business logic.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import Settings, get_settings


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter returns an error or an unparseable response."""


class OpenRouterClient:
    """Minimal async client for OpenRouter chat/completions."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.settings = settings or get_settings()
        self._timeout = timeout
        # An injected client (e.g. for tests) is not owned by us and won't be
        # closed by ``aclose``.
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "OpenRouterClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.0,
        **extra: Any,
    ) -> dict[str, Any]:
        """POST a chat/completions request and return the parsed JSON body."""
        if not self.settings.openrouter_api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not configured")

        url = f"{self.settings.openrouter_base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": model or self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            **extra,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._get_client().post(
                url, json=payload, headers=headers
            )
        except httpx.HTTPError as exc:  # network/timeout
            raise OpenRouterError(f"request to OpenRouter failed: {exc}") from exc

        if response.status_code >= 400:
            raise OpenRouterError(
                f"OpenRouter returned {response.status_code}: {response.text[:500]}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise OpenRouterError("OpenRouter returned non-JSON body") from exc

    async def send_text_and_image(
        self,
        text: str,
        image_data_url: str,
        *,
        model: str | None = None,
        response_format: dict[str, Any] | None = None,
        **extra: Any,
    ) -> str:
        """Send one multimodal user message and return the assistant text.

        ``image_data_url`` should be a ``data:`` URL (e.g.
        ``data:image/png;base64,...``). Returns the assistant message content.
        """
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url},
                    },
                ],
            }
        ]
        body = await self.chat(
            messages,
            model=model,
            response_format=response_format,
            **extra,
        )
        return _extract_assistant_text(body)


def _extract_assistant_text(body: dict[str, Any]) -> str:
    """Pull the assistant text out of a chat/completions response body."""
    try:
        choices = body["choices"]
        message = choices[0]["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError(
            f"unexpected OpenRouter response shape: {body!r:.300}"
        ) from exc

    # Content is usually a plain string, but some providers return a list of
    # content parts — concatenate any text parts in that case.
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "".join(parts)
    raise OpenRouterError(f"unexpected assistant content type: {type(content)!r}")
