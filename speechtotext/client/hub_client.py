"""Signed HTTP client for a paired hub.

All requests carry the v2 signature headers. The message bytes come from
:func:`speechtotext.api.auth.build_signed_message` — the same function the
hub verifies with, so client and server can never drift.

Uploads hash the file in one pass to build the signature, then stream the
file as the request body (two sequential disk reads, zero full-file RAM).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from speechtotext.api.auth import build_signed_message

_CHUNK = 64 * 1024


def signed_headers(
    signing_key,
    device_id: str,
    method: str,
    path_with_query: str,
    body: bytes = b"",
    *,
    body_sha256: bytes | None = None,
) -> dict[str, str]:
    """v2 signature headers. ``path_with_query`` may include ``?query``.

    Pass ``body_sha256`` for streaming bodies (digest precomputed); else
    the digest is taken over ``body``.
    """
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    path, _, query = path_with_query.partition("?")
    digest = body_sha256 or hashlib.sha256(body).digest()
    msg = build_signed_message(method, path, query, ts, nonce, digest)
    sig = signing_key.sign(msg).signature
    return {
        "X-Device-Id": device_id,
        "X-Signature-B64": base64.b64encode(sig).decode("ascii"),
        "X-Timestamp": ts,
        "X-Nonce": nonce,
    }


def _file_sha256(path: Path) -> bytes:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.digest()


class HubClient:
    """Thin synchronous client. One instance per joined hub."""

    def __init__(
        self,
        base_url: str,
        device_id: str,
        signing_key,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self._sk = signing_key
        self._http = httpx.Client(
            base_url=self.base_url, timeout=timeout, transport=transport
        )

    def get_json(self, path_with_query: str) -> Any:
        headers = signed_headers(
            self._sk, self.device_id, "GET", path_with_query
        )
        resp = self._http.get(path_with_query, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def patch_json(self, path: str, body: dict) -> Any:
        import json as _json

        raw = _json.dumps(body).encode("utf-8")
        headers = signed_headers(self._sk, self.device_id, "PATCH", path, raw)
        headers["Content-Type"] = "application/json"
        resp = self._http.request("PATCH", path, content=raw, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def upload_audio(self, audio_path: Path) -> Any:
        # The file must not change between this hashing pass and the
        # streamed read below — a mismatch makes the hub reject with 401.
        digest = _file_sha256(audio_path)
        size = audio_path.stat().st_size
        target = f"/jobs/upload?filename={quote(audio_path.name, safe='')}"
        headers = signed_headers(
            self._sk, self.device_id, "POST", target, body_sha256=digest
        )
        headers["Content-Length"] = str(size)
        headers["Content-Type"] = "application/octet-stream"

        def _stream():
            with audio_path.open("rb") as fh:
                while chunk := fh.read(_CHUNK):
                    yield chunk

        resp = self._http.post(target, content=_stream(), headers=headers)
        resp.raise_for_status()
        return resp.json()

    def post_json(self, path: str, body: dict) -> Any:
        import json as _json

        raw = _json.dumps(body).encode("utf-8")
        headers = signed_headers(self._sk, self.device_id, "POST", path, raw)
        headers["Content-Type"] = "application/json"
        resp = self._http.post(path, content=raw, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def import_transcript(self, json_path: Path, audio_path: Path | None) -> Any:
        """Two-step transcript import: stage audio (if any), then commit."""
        import json as _json

        audio_ref = None
        audio_filename = None
        if audio_path is not None and audio_path.is_file():
            digest = _file_sha256(audio_path)
            size = audio_path.stat().st_size
            target = (
                "/transcripts/import/audio"
                f"?filename={quote(audio_path.name, safe='')}"
            )
            headers = signed_headers(
                self._sk, self.device_id, "POST", target, body_sha256=digest
            )
            headers["Content-Length"] = str(size)
            headers["Content-Type"] = "application/octet-stream"

            def _stream():
                with audio_path.open("rb") as fh:
                    while chunk := fh.read(_CHUNK):
                        yield chunk

            resp = self._http.post(target, content=_stream(), headers=headers)
            resp.raise_for_status()
            audio_ref = resp.json()["audio_ref"]
            audio_filename = audio_path.name

        doc = _json.loads(json_path.read_text(encoding="utf-8"))
        return self.post_json("/transcripts/import", {
            "tid": json_path.stem,
            "transcript": doc,
            "audio_ref": audio_ref,
            "audio_filename": audio_filename,
        })

    def close(self) -> None:
        self._http.close()
