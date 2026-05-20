"""Hub-side pairing token mint + exchange.

Pairing flow (architecture plan §3.5):

1. Hub UI calls :meth:`PairingTokenStore.mint` (via the
   ``POST /pair/tokens`` endpoint) and renders the resulting token as
   a QR code on screen.
2. New device scans the QR. Together with the workspace_id and hub
   URL (which travel in the QR body), it generates its own Ed25519
   keypair and POSTs to ``/v1/pair`` with the token + its public key.
3. Hub validates the token (single-use, 5-minute TTL), sealedboxes
   the workspace symmetric key ``W`` to the device's pubkey (via
   Ed25519 → Curve25519 conversion), and returns the sealed payload
   along with a freshly assigned device_id.
4. Device decrypts ``W`` with its private key, stores it in its
   secure storage, and is now part of the workspace.

The token store is in-memory only — the hub runs as a single process
and pairing tokens are extremely short-lived. Across a hub restart
any in-flight tokens are lost; users re-issue. That's fine.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

TOKEN_TTL_SECONDS = 5 * 60  # 5 minutes


@dataclass(frozen=True)
class PairingToken:
    """A single-use pairing token with a fixed TTL."""

    token: str
    created_at: float  # unix epoch seconds

    def is_expired(self, *, now: float | None = None) -> bool:
        return (now or time.time()) - self.created_at >= TOKEN_TTL_SECONDS


class PairingTokenStore:
    """In-memory pairing token registry.

    Operations are thread-safe so the FastAPI request thread and any
    background cleanup routine can coexist. ``mint`` returns a freshly
    minted token; ``consume`` either returns the (now-deleted) token
    record or raises with a structured reason.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, PairingToken] = {}
        self._consumed: set[str] = set()
        self._lock = threading.Lock()

    def mint(self) -> PairingToken:
        token_str = secrets.token_hex(16)  # 16 bytes -> 32 hex chars
        tok = PairingToken(token=token_str, created_at=time.time())
        with self._lock:
            self._tokens[token_str] = tok
        return tok

    def consume(
        self, token_str: str, *, now: float | None = None
    ) -> PairingToken:
        """Single-use consume of a token.

        Raises ``ValueError`` with a structured ``code`` attribute
        encoded in the message: "unknown", "consumed", or "expired".
        Callers map these to HTTP statuses.
        """
        with self._lock:
            if token_str in self._consumed:
                raise ValueError("consumed: token already consumed")
            tok = self._tokens.get(token_str)
            if tok is None:
                raise ValueError("unknown: token not recognised")
            if tok.is_expired(now=now):
                # Move from active to consumed so a stale token cannot
                # be replayed if the wall clock jitters back.
                self._consumed.add(token_str)
                del self._tokens[token_str]
                raise ValueError("expired: token past 5-minute TTL")
            self._consumed.add(token_str)
            del self._tokens[token_str]
            return tok

    def purge_expired(self, *, now: float | None = None) -> int:
        """Drop expired tokens from active storage; return count purged."""
        now = now or time.time()
        with self._lock:
            expired = [
                t for t, tok in self._tokens.items() if tok.is_expired(now=now)
            ]
            for t in expired:
                self._consumed.add(t)
                del self._tokens[t]
            return len(expired)


def new_device_id() -> str:
    """Allocate a fresh hub-assigned device_id for a pairing.

    Format: ``dev-<12 hex chars>``. Centralised here so block 5c's
    devices table uses the same shape.
    """
    return f"dev-{secrets.token_hex(6)}"
