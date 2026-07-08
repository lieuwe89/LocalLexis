from __future__ import annotations

import json

import httpx
import pytest

from speechtotext.config import SummarizeConfig
from speechtotext.summarize.provider import (
    OpenAICompatProvider,
    ProviderError,
    provider_from_config,
)


def _transport(handler):
    return httpx.MockTransport(handler)


def test_chat_posts_openai_shape_and_returns_content():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "A summary."}}]
        })

    p = OpenAICompatProvider(
        base_url="http://127.0.0.1:13305/api/v1",
        api_key="k",
        model="Qwen3-8B-GGUF",
        transport=_transport(handler),
    )
    out = p.chat([{"role": "user", "content": "hi"}])
    assert out == "A summary."
    assert seen["url"] == "http://127.0.0.1:13305/api/v1/chat/completions"
    assert seen["body"]["model"] == "Qwen3-8B-GGUF"
    assert seen["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert seen["auth"] == "Bearer k"


def test_chat_no_api_key_sends_no_auth_header():
    def handler(req: httpx.Request) -> httpx.Response:
        assert "authorization" not in req.headers
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}]
        })

    p = OpenAICompatProvider(base_url="http://x/v1", model="m",
                             transport=_transport(handler))
    assert p.chat([{"role": "user", "content": "q"}]) == "ok"


def test_chat_http_error_raises_provider_error():
    def handler(req):
        return httpx.Response(500, text="boom")

    p = OpenAICompatProvider(base_url="http://x/v1", model="m",
                             transport=_transport(handler))
    with pytest.raises(ProviderError, match="500"):
        p.chat([{"role": "user", "content": "q"}])


def test_chat_malformed_response_raises_provider_error():
    def handler(req):
        return httpx.Response(200, json={"unexpected": True})

    p = OpenAICompatProvider(base_url="http://x/v1", model="m",
                             transport=_transport(handler))
    with pytest.raises(ProviderError, match="malformed"):
        p.chat([{"role": "user", "content": "q"}])


def test_list_models():
    def handler(req):
        assert str(req.url).endswith("/models")
        return httpx.Response(200, json={"data": [{"id": "m1"}, {"id": "m2"}]})

    p = OpenAICompatProvider(base_url="http://x/v1", model="m",
                             transport=_transport(handler))
    assert p.list_models() == ["m1", "m2"]


def test_provider_from_config():
    cfg = SummarizeConfig(provider="lemonade", base_url="http://h:13305/api/v1/",
                          model="M", api_key=None)
    p = provider_from_config(cfg)
    assert p.base_url == "http://h:13305/api/v1"  # trailing slash stripped
    assert p.model == "M"
