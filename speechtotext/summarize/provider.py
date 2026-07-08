"""LLM provider abstraction for transcript summarization.

One implementation covers Lemonade, OpenRouter, and any other server
that speaks the OpenAI chat-completions API — switching providers is a
config change (base_url/model/api_key), never a code change. The
Protocol exists so a genuinely different wire protocol can slot in
later without touching call sites.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from speechtotext.config import SummarizeConfig


class ProviderError(RuntimeError):
    """Provider unreachable, rejected the request, or answered garbage."""


class LlmProvider(Protocol):
    def chat(self, messages: list[dict]) -> str: ...
    def list_models(self) -> list[str]: ...


class OpenAICompatProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            headers=self._headers, timeout=self._timeout, transport=self._transport
        )

    def chat(self, messages: list[dict]) -> str:
        try:
            with self._client() as client:
                r = client.post(
                    f"{self.base_url}/chat/completions",
                    json={"model": self.model, "messages": messages},
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"provider returned {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"cannot reach provider: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"malformed provider response: {repr(data)[:500]}"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("malformed provider response: empty content")
        return content

    def list_models(self) -> list[str]:
        try:
            with self._client() as client:
                r = client.get(f"{self.base_url}/models")
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"cannot list models: {exc}") from exc
        return [
            str(m["id"])
            for m in (data.get("data") or [])
            if isinstance(m, dict) and m.get("id")
        ]


def provider_from_config(cfg: SummarizeConfig) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        base_url=cfg.base_url, model=cfg.model, api_key=cfg.api_key
    )
