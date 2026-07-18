from __future__ import annotations

import sys

import numpy as np
import pytest

from speechtotext.rag import embedder as mod


class _FakeModel:
    def encode(self, texts, normalize_embeddings=True, convert_to_numpy=True):
        # deterministic 4-dim unit vectors keyed on text length
        out = []
        for t in texts:
            v = np.array([len(t), 1.0, 0.0, 0.0], dtype=np.float64)
            out.append(v / np.linalg.norm(v))
        return np.vstack(out)


def test_embed_returns_float32_normalized(monkeypatch):
    e = mod.Embedder()
    monkeypatch.setattr(e, "_load", lambda: _FakeModel())
    vecs = e.embed(["hallo", "langere zin hier"])
    assert vecs.dtype == np.float32
    assert vecs.shape == (2, 4)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-5)


def test_load_failure_raises_embedder_error(monkeypatch):
    e = mod.Embedder(model_name="nonexistent/nope")

    def boom():
        raise mod.EmbedderError("embedding model unavailable: x")

    monkeypatch.setattr(e, "_load", boom)
    with pytest.raises(mod.EmbedderError):
        e.embed(["hallo"])


def test_real_load_wraps_import_failure(monkeypatch):
    # Poisoning the sys.modules entry makes `import sentence_transformers`
    # raise ImportError even after the package is installed, so the real
    # _load() error path stays covered in every environment.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    e = mod.Embedder()
    with pytest.raises(mod.EmbedderError):
        e._load()


def test_get_embedder_is_singleton():
    a = mod.get_embedder()
    b = mod.get_embedder()
    assert a is b


def _fake_st_module(calls, local_ok, network_ok):
    """Build a fake sentence_transformers module recording call kwargs.

    local_ok/network_ok control whether the local_files_only=True call and
    the plain (network) call succeed or raise.
    """
    class _Model:
        def __init__(self, name, **kwargs):
            self.name = name
            self.kwargs = kwargs

    def SentenceTransformer(name, **kwargs):
        calls.append(kwargs)
        local_files_only = kwargs.get("local_files_only", False)
        ok = local_ok if local_files_only else network_ok
        if not ok:
            raise OSError("simulated failure")
        return _Model(name, **kwargs)

    import types
    return types.SimpleNamespace(SentenceTransformer=SentenceTransformer)


def test_load_tries_local_files_only_first_then_falls_back_to_network(monkeypatch):
    calls: list[dict] = []
    fake_mod = _fake_st_module(calls, local_ok=False, network_ok=True)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)

    e = mod.Embedder()
    model = e._load()

    assert len(calls) == 2
    assert calls[0].get("local_files_only") is True
    assert "local_files_only" not in calls[1]
    assert model.name == e.model_name


def test_load_uses_cached_model_with_zero_network_call_when_local_load_succeeds(monkeypatch):
    calls: list[dict] = []
    fake_mod = _fake_st_module(calls, local_ok=True, network_ok=True)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)

    e = mod.Embedder()
    e._load()

    assert len(calls) == 1
    assert calls[0].get("local_files_only") is True


def test_load_raises_embedder_error_when_both_local_and_network_fail(monkeypatch):
    calls: list[dict] = []
    fake_mod = _fake_st_module(calls, local_ok=False, network_ok=False)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)

    e = mod.Embedder()
    with pytest.raises(mod.EmbedderError):
        e._load()
    assert len(calls) == 2
