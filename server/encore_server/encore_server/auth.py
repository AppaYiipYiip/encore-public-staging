"""Who is asking (docs/04 `accounts`, docs/17 section 1, docs/21).

Two ways in:

* A **device token** (`Authorization: Bearer ...`): made once at sign-in, kept by the app instead of the password, revocable per device.
  Only its hash is stored here.
* The music server's **Subsonic token** (`u`, `t`, `s`, in the query or as `X-Encore-*` headers): what the apps send today. It is checked
  with the music server (which keeps the passwords) and the answer is remembered for ten minutes.

The password itself is never stored; at sign-in it is turned into a Subsonic token, checked once, and dropped.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx

from .errors import ApiError
from .ids import new_id, now_ms
from .login_vouch import VouchStore

log = logging.getLogger("encore_server.auth")

_USER = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
_TOKEN = re.compile(r"^[0-9a-fA-F]{32}$")
_SALT = re.compile(r"^[A-Za-z0-9]{4,64}$")

VERIFY_TTL_S = 600.0

#: How long a login the music server ACCEPTED is remembered as "a device this server already knows" (P3-34 slice 2a): long enough that the owner's app still answers when a stranger's
#: guesses are being slowed (the ten minutes of [VERIFY_TTL_S] are not), and renewed by every use. It only skips the guess limits' refusals, never the music server's own check.
VOUCH_TTL_S = 24 * 3600.0
VOUCH_CAP = 5000
#: At most this many remembered logins for one name: a member who sends the right password with a fresh salt on every call must not push the owner's out of the memory.
VOUCH_PER_NAME = 32
#: A remembered login that is used again is written to the database again at most this often (the memory in the process is renewed by every use).
VOUCH_RENEW_S = 3600.0

#: The Subsonic error codes that mean "that login is no good": wrong username or password (40), token authentication not supported for this
#: account (41), a mechanism that is not supported (42, 43) and a wrong API key (44). Any other answer says nothing about the login.
_REFUSED = frozenset({40, 41, 42, 43, 44})


class MusicServerUnavailable(Exception):
    """The music server gave no answer (not there, restarting, an error page, a 5xx). That says nothing about the password: it is neither a yes nor
    a no, and it is answered as a retryable 503 that is not counted as a guess and signs nobody out (AUDIT B-41)."""


@dataclass(frozen=True)
class Principal:
    person_id: str
    navidrome_user: str
    role: str
    device_id: str | None = None


class Verifier(Protocol):
    def verify(self, user: str, token: str, salt: str) -> bool: ...

    def is_admin(self, user: str, token: str, salt: str) -> bool: ...


class NavidromeVerifier:
    """Asks the music server whether a Subsonic token is good; remembers a yes for [ttl] seconds."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        ttl: float = VERIFY_TTL_S,
        clock: Callable[[], float] = time.monotonic,
        vouch_ttl: float = VOUCH_TTL_S,
        vouch_cap: int = VOUCH_CAP,
        vouch_per_name: int = VOUCH_PER_NAME,
        store: VouchStore | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=8.0)
        self._ttl = ttl
        self._clock = clock
        self._ok: dict[tuple[str, str, str], float] = {}
        # The longer memory (see [vouched]): a keyed digest of the credentials, made with a key that never leaves the server, so what is held is of no use outside it and holds no token, salt or
        # name in the clear; the name is kept apart, in lower case, only so that [forget] can drop a person's entries. With a [store] the memory survives a restart (the key and the rows are in
        # the database, loaded at first use, once the database is migrated); without one it lives and dies with this process.
        self._vouch_ttl = vouch_ttl
        self._vouch_cap = vouch_cap
        self._vouch_per_name = vouch_per_name
        self._vouch_key = secrets.token_bytes(32)
        self._vouched: dict[bytes, tuple[str, float]] = {}
        self._written: dict[bytes, float] = {}  # digest -> wall-clock seconds of its last write to the store
        self._store = store
        self._wall = wall_clock
        self._loaded = store is None
        self._vouch_lock = threading.RLock()

    def _call(self, method: str, user: str, token: str, salt: str, **extra: str) -> dict[str, object]:
        """The music server's answer, or [MusicServerUnavailable] when it gave none a login can be judged by."""
        params = {"u": user, "t": token, "s": salt, "v": "1.16.1", "c": "encore-server", "f": "json", **extra}
        try:
            response = self._client.get(f"{self._base}/rest/{method}", params=params)
            if response.status_code >= 500:
                raise MusicServerUnavailable(f"the music server answered {response.status_code}")
            body = response.json().get("subsonic-response")
        except (httpx.HTTPError, ValueError, AttributeError) as error:
            raise MusicServerUnavailable("the music server did not answer") from error
        if not isinstance(body, dict):
            raise MusicServerUnavailable("the music server's answer was not understood")
        return body

    def _ensure_loaded(self) -> None:
        """Reads the key and the rows of the store once, at first use (the database is migrated by then). A store that cannot be read leaves this process with a memory of its own."""
        if self._loaded:
            return
        with self._vouch_lock:
            if self._loaded:
                return
            self._loaded = True
            assert self._store is not None
            try:
                key = self._store.key()
                wall = self._wall()
                rows = self._store.load(int((wall - self._vouch_ttl) * 1000))
            except Exception as error:  # noqa: BLE001 - whatever the store fails with, the request that is being signed in goes on
                log.warning("the remembered logins could not be read (%s): this process starts with none", type(error).__name__)
                self._store = None
                return
            self._vouch_key = key
            mono = self._clock()
            for digest, name, at_ms in rows:
                self._vouched[digest] = (name, mono - (wall - at_ms / 1000))
                self._written[digest] = at_ms / 1000

    def _persist(self, action: Callable[[VouchStore], None]) -> None:
        """Runs one write on the store, as a best effort: whatever it fails with, the login that is being checked goes on (the memory in this process is the one that counts)."""
        store = self._store
        if store is None:
            return
        try:
            action(store)
        except Exception as error:  # noqa: BLE001 - a store may fail in any way; a remembered login is never worth a refused one
            log.debug("a remembered login could not be kept (%s): it stays in memory only", type(error).__name__)

    def _persist_drop(self, digest: bytes) -> None:
        self._persist(lambda store: store.drop(digest))

    def _fingerprint(self, user: str, token: str, salt: str) -> bytes:
        self._ensure_loaded()
        return hmac.new(self._vouch_key, f"{user.lower()}\0{token}\0{salt}".encode(), hashlib.sha256).digest()

    def _vouch(self, user: str, token: str, salt: str) -> None:
        digest = self._fingerprint(user, token, salt)
        name = user.lower()
        now, wall = self._clock(), self._wall()
        dropped: list[bytes] = []
        with self._vouch_lock:
            fresh = digest not in self._vouched
            self._vouched[digest] = (name, now)
            if fresh:
                same = sorted((d for d, e in self._vouched.items() if e[0] == name), key=lambda d: self._vouched[d][1])
                dropped += same[: max(0, len(same) - self._vouch_per_name)]
                if len(self._vouched) - len(dropped) > self._vouch_cap:
                    live = sorted((d for d in self._vouched if d not in dropped), key=lambda d: self._vouched[d][1])
                    stale = [d for d in live if now - self._vouched[d][1] >= self._vouch_ttl]
                    dropped += stale
                    over = len(self._vouched) - len(dropped) - self._vouch_cap
                    dropped += [d for d in live if d not in stale][: max(0, over)]
                for d in dropped:
                    self._vouched.pop(d, None)
                    self._written.pop(d, None)
            last = self._written.get(digest)
            write = last is None or wall - last >= VOUCH_RENEW_S
            if write:
                self._written[digest] = wall
        for d in dropped:
            self._persist_drop(d)
        if write:
            self._persist(lambda store: store.put(digest, name, int(wall * 1000)))

    def note_accepted(self, user: str, token: str, salt: str) -> None:
        """The gateway saw the music server ACCEPT this login at the home door (P3-34 slice 2b): it is a device this server now knows, exactly as if [verify] had asked. [token] and [salt] are the
        `t` and `s` of a token login, or `p:` and the password as written and an empty salt for a plain one: they only ever go into the keyed digest."""
        self._vouch(user, token, salt)

    def drop_vouch(self, user: str, token: str, salt: str) -> None:
        """The gateway saw the music server REFUSE a login that was known: it was good once and is not any more (the password changed), a guess like any other from now on."""
        digest = self._fingerprint(user, token, salt)
        with self._vouch_lock:
            known = self._vouched.pop(digest, None) is not None
            self._written.pop(digest, None)
        if known:
            self._persist_drop(digest)

    def vouched(self, user: str, token: str, salt: str) -> bool:
        """Is this a device the server already knows: a login the music server ACCEPTED within the last day (P3-34 slice 2a, docs/21)? Such a login skips the refusals of the guess limits (the
        address that everybody behind a hiding Docker shares, and the account), and NOTHING else: the music server still checks it. Kept across a restart; [forget] drops a person's."""
        entry = self._vouched.get(self._fingerprint(user, token, salt))
        return entry is not None and self._clock() - entry[1] < self._vouch_ttl

    def known_good(self, user: str, token: str, salt: str) -> bool:
        """Has the music server already said yes to exactly these credentials, a moment ago? Such a login is never held up by a limit: the limit is
        for guesses, and a guess is by definition not a login the music server has vouched for (AUDIT B1)."""
        seen = self._ok.get((user, token, salt))
        known = seen is not None and self._clock() - seen < self._ttl
        if known:
            self._vouch(user, token, salt)  # a device that keeps being known keeps its day
        return known

    def forget(self, user: str) -> None:
        """Drops what is remembered about [user]: after the person was removed or locked, or their password changed, the music server's earlier
        yes must not carry on for the ten minutes it is kept (AUDIT B4)."""
        wanted = user.lower()
        for key in [k for k in self._ok if k[0].lower() == wanted]:
            del self._ok[key]
        self._ensure_loaded()
        with self._vouch_lock:
            for digest in [d for d, entry in self._vouched.items() if entry[0] == wanted]:
                del self._vouched[digest]
                self._written.pop(digest, None)
        self._persist(lambda store: store.drop_name(wanted))

    def verify(self, user: str, token: str, salt: str) -> bool:
        key = (user, token, salt)
        seen = self._ok.get(key)
        if seen is not None and self._clock() - seen < self._ttl:
            self._vouch(user, token, salt)
            return True
        body = self._call("ping", user, token, salt)
        if body.get("status") == "ok":
            self._ok[key] = self._clock()
            if len(self._ok) > 2000:
                self._ok = {k: v for k, v in self._ok.items() if self._clock() - v < self._ttl}
            self._vouch(user, token, salt)
            return True
        error = body.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if code in _REFUSED:
            # it was good once and is not any more (the password changed): a guess like any other
            digest = self._fingerprint(user, token, salt)
            with self._vouch_lock:
                known = self._vouched.pop(digest, None) is not None
                self._written.pop(digest, None)
            if known:
                self._persist_drop(digest)
            return False
        # A "failed" with any other code (or none) is not the music server saying the login is wrong: nobody is told so.
        raise MusicServerUnavailable(f"the music server could not check the login (code {code!r})")

    def is_admin(self, user: str, token: str, salt: str) -> bool:
        body = self._call("getUser", user, token, salt, username=user)
        found = body.get("user")
        return bool(isinstance(found, dict) and found.get("adminRole"))


def subsonic_token(password: str, salt: str) -> str:
    return hashlib.md5((password + salt).encode()).hexdigest()  # noqa: S324 - the Subsonic protocol's own token


def subsonic_credentials(query: dict[str, str], headers: dict[str, str]) -> tuple[str, str, str] | None:
    lower = {k.lower(): v for k, v in headers.items()}
    user = query.get("u") or lower.get("x-encore-user") or ""
    token = query.get("t") or lower.get("x-encore-token") or ""
    salt = query.get("s") or lower.get("x-encore-salt") or ""
    if _USER.match(user) and _TOKEN.match(token) and _SALT.match(salt):
        return user, token.lower(), salt
    return None


def new_device_token() -> str:
    return "ed_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_device(conn, person_id: str, name: str, kind: str = "phone", app_version: str | None = None) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """A new device for a person. Returns (device id, the token, shown once: only its hash is kept)."""
    device_id = new_id("dv")
    token = new_device_token()
    conn.execute(
        "INSERT INTO device (id, person, name, kind, token_hash, app_version, created_at, last_seen) VALUES (?,?,?,?,?,?,?,?)",
        (
            device_id,
            person_id,
            " ".join(name.split())[:80] or "Phone",
            kind if kind in {"phone", "tablet", "web", "pc", "other"} else "other",
            hash_token(token),
            app_version,
            now_ms(),
            now_ms(),
        ),
    )
    return device_id, token


def forget_credentials(verifier: object, user: str | None) -> None:
    """Tells a verifier that keeps a memory of yeses to forget [user] (a verifier without one has nothing to forget)."""
    forget = getattr(verifier, "forget", None)
    if user and callable(forget):
        forget(user)


def person_may_listen(conn, person: str) -> bool:  # type: ignore[no-untyped-def]
    """A signed address (a song, a cover pass) was made for somebody who is still here and not locked out: it is worth what its person is worth,
    however much of its six hours or seven days is left (AUDIT B13)."""
    return conn.execute("SELECT 1 FROM person WHERE id = ? AND locked = 0", (person,)).fetchone() is not None


def bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    return token if token.startswith("ed_") and len(token) < 200 else None


def require(principal: Principal | None) -> Principal:
    if principal is None:
        raise ApiError("unauthorized")
    return principal


# ---- signed stream addresses (docs/17 section 1): a player cannot always set headers, so the address carries a signature.

#: How long a stream address works. Long, because a player keeps using the same address for a whole listen (a two-hour recitation).
#: A browser is signed in for a short while (docs/36 section 2): the page keeps its device token for the life of the tab, and the server ends a browser
#: device ("web") that has not been used for this long, or that is older than this, whatever the tab says. A phone is a device that stays.
WEB_SESSION_IDLE_MS = 12 * 3600 * 1000
WEB_SESSION_LIFETIME_MS = 7 * 24 * 3600 * 1000


def web_session_over(created_ms: int, seen_ms: int | None, now: int) -> bool:
    """Is a browser device past either limit? `seen_ms` is written at most once a minute, so the idle limit is exact to the minute."""
    return (
        now - (seen_ms if seen_ms is not None else created_ms) > WEB_SESSION_IDLE_MS or now - created_ms > WEB_SESSION_LIFETIME_MS
    )


STREAM_URL_TTL_S = 6 * 3600

#: How long a cover pass works: a week. One pass opens every picture (a screen shows thirty), so the phone asks for it rarely.
COVER_PASS_TTL_S = 7 * 24 * 3600

#: What a cover pass is signed over, in place of one picture's id (a song address cannot be mistaken for it: no ref has this id).
COVER_PASS_SCOPE = "cover-pass:*"


def stream_secret(conn) -> bytes:  # type: ignore[no-untyped-def]
    """The server's secret for signing addresses: made once, kept in the database."""
    row = conn.execute("SELECT value FROM setting WHERE key = 'stream_secret'").fetchone()
    if row is not None:
        return bytes.fromhex(row["value"])
    secret = secrets.token_bytes(32)
    conn.execute("INSERT OR IGNORE INTO setting (key, value) VALUES ('stream_secret', ?)", (secret.hex(),))
    row = conn.execute("SELECT value FROM setting WHERE key = 'stream_secret'").fetchone()
    return bytes.fromhex(row["value"])


def sign_stream(secret: bytes, person: str, ref: str, expires_s: int) -> str:
    return hmac.new(secret, f"{person}|{ref}|{expires_s}".encode(), hashlib.sha256).hexdigest()[:32]


def valid_stream_signature(secret: bytes, person: str, ref: str, expires_s: int, sig: str, *, now_s: float | None = None) -> bool:
    if expires_s < (now_s if now_s is not None else time.time()):
        return False
    return hmac.compare_digest(sign_stream(secret, person, ref, expires_s), sig)
