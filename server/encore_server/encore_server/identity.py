"""Who this server is: an Ed25519 key made once, and an id that is the hash of its public half (docs/11 ADR-R40).

A phone must be able to tell *its* server from whatever else answers at an address (a recycled address on another network, a copied id in an
advertisement), so the identity is the key itself: the id is `base32(sha256(public key)[:16])`, anybody can recompute it from the public key, and only
the server can sign a fresh challenge. The key lives in the database (table `setting`), so a backup restored on a new computer is the same server.

`GET /info?challenge=<nonce>` answers with the id, the public key and a signature over the id and the nonce. The app sends no login and no token
until an address has answered correctly. This proves who answers, not that the path is private: cleartext http on a home network stays the
accepted limit (docs/21).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import sqlite3

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SETTING_KEY = "server_key"
#: A challenge is a fresh random string the app makes; bounded so nobody gets a signature over something chosen freely and long.
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_DOMAIN = b"encore.info.v1\n"


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def server_id_for(public_key: bytes) -> str:
    """26 characters of lower-case base32: the first 128 bits of the key's SHA-256."""
    return base64.b32encode(hashlib.sha256(public_key).digest()[:16]).decode().lower().rstrip("=")


def challenge_message(server_id: str, nonce: str) -> bytes:
    return _DOMAIN + server_id.encode() + b"\n" + nonce.encode()


class ServerIdentity:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private = private_key
        self.public_key = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.server_id = server_id_for(self.public_key)

    def sign(self, nonce: str) -> str:
        """The signature (base64url) over this server's id and [nonce]."""
        return b64u(self._private.sign(challenge_message(self.server_id, nonce)))

    def public_fields(self) -> dict[str, str]:
        return {"serverId": self.server_id, "publicKey": b64u(self.public_key)}

    def answer(self, nonce: str) -> dict[str, str]:
        return {**self.public_fields(), "signature": self.sign(nonce)}


def load_or_create(conn: sqlite3.Connection) -> ServerIdentity:
    """The server's identity from the database; made on first use. Two starts at once end with the same key (`INSERT OR IGNORE`, then read back)."""
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (SETTING_KEY,)).fetchone()
    if row is None:
        raw = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
        )
        conn.execute("INSERT OR IGNORE INTO setting (key, value) VALUES (?, ?)", (SETTING_KEY, raw.hex()))
        row = conn.execute("SELECT value FROM setting WHERE key = ?", (SETTING_KEY,)).fetchone()
    return ServerIdentity(Ed25519PrivateKey.from_private_bytes(bytes.fromhex(row["value"])))


def verify(*, server_id: str, public_key: str, nonce: str, signature: str) -> bool:
    """What a phone does with an answer: the key must hash to the id it expects, and the signature over *its own* nonce must verify.
    Anything malformed is simply "no"."""
    try:
        key = unb64u(public_key)
        if server_id_for(key) != server_id:
            return False
        Ed25519PublicKey.from_public_bytes(key).verify(unb64u(signature), challenge_message(server_id, nonce))
    except (InvalidSignature, ValueError, binascii.Error):
        return False
    return True
