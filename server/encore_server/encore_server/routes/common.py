"""What every route module shares: the services of a request, who is asking, the answer shapes and the address of the asker (docs/17 section 1)."""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .. import (
    library,
    netaddr,
    subsonic_guard,
)
from ..accounts import Accounts, Attempt, Limiter, LoginGuard
from ..artist_finder import ArtistFinder
from ..auth import (
    Principal,
    Verifier,
    bearer_token,
    hash_token,
    subsonic_credentials,
    web_session_over,
)
from ..catalogue import Catalogue
from ..config import Settings
from ..db import Database
from ..errors import ApiError
from ..helper import HelperClient
from ..identity import ServerIdentity
from ..ids import is_id, now_ms
from ..imports.service import ImportService
from ..imports.watch import ImportWatch
from ..keep_watch import KeepWatch
from ..keeper.failures import describe_failure, describe_wait
from ..keeper.keeper import Keeper
from ..keeper.triggers import want_kept as _want_kept
from ..live import Hub
from ..migration import SubsonicUser
from ..navidrome import NavidromeClient
from ..notifications import Notifications
from ..scanner import LibraryLinker
from ..scheduler import Scheduler
from ..sources.youtube.source import YoutubeSource
from ..sources.youtube.updater import Tools

log = logging.getLogger("encore_server.api")


API_PREFIX = "/encore/api/v1"

FEATURES = ["library", "playback", "live", "refs", "unavailable-ids", "ref-gone", "my-plays"]
#: What a server that keeps songs adds: `keep` (the song-by-song calls and `keep/progress`, `keep/watch`, `keep/retry`), `keep-ask` (`POST keep/ask`, a
#: whole download asked for at once) and `import-kept` (`import.progress` is pushed when a song of an import is STORED too, not only when one is matched: a phone that finds
#: the word may stop asking `GET imports` every few seconds, N-43). An app that finds a feature missing does without it; it never tries a route to find out (docs/17 "Versions").
KEEP_FEATURES = ["keep", "keep-ask", "import-kept"]
#: What a server whose Host has not switched the catalogue off adds (`ENCORE_CATALOGUE=0`): the routes under `catalogue/` (docs/17 section 3).
CATALOGUE_FEATURES = ["catalogue"]


@dataclass
class Services:
    settings: Settings
    db: Database
    hub: Hub
    verifier: Verifier
    youtube: YoutubeSource | None = None
    scheduler: Scheduler | None = None
    keeper: Keeper | None = None
    linker: LibraryLinker | None = None
    imports: ImportService | None = None
    accounts: Accounts | None = None
    notifications: Notifications | None = None
    limiter: Limiter | None = None
    music_as: Callable[[str, str, str], SubsonicUser] | None = None
    #: The yt-dlp updater and the restart that waits for a quiet moment (docs/11 ADR-R39); `None` when off.
    tools: Tools | None = None
    #: Who this server is: its key and the id made from it (docs/11 ADR-R40).
    identity: ServerIdentity | None = None
    #: The music server as this server's own account: kept songs and covers are passed on through it, so a phone needs no login of the music server.
    music: NavidromeClient | None = None
    #: The secret that signs song and picture addresses. Made once and never changed, so it is read once at start: a screen shows thirty pictures,
    #: and each of those requests used to open a write transaction just to read it.
    #: **If a way to change it is ever added** (a "sign out everywhere" that also invalidates handed-out addresses, a leaked key), that change must
    #: replace THIS copy too: the database row is no longer read per request, so changing only the row would leave the old key signing and checking.
    stream_key: bytes = b""
    #: Tells a device how its downloads are going (`PUT keep/watch`, the live event `keep.progress`); `None` when this server does not keep songs.
    keep_watch: KeepWatch | None = None
    #: Tells a person's devices when a song of an import is stored (`import.progress`, N-43); `None` when this server does not keep songs.
    import_watch: ImportWatch | None = None
    #: Finds pictures for the artists the music server has none for (N-15); one of the background errands, `None` when there is no music-server account.
    artist_finder: ArtistFinder | None = None
    #: What the phones' search, artist and album pages are answered from (P2-12): the one gate to the catalogue, its cache and its shapes.
    catalogue: Catalogue | None = None
    #: Makes the music server's account for the owner of a server that is being set up in the browser (`setup.run_setup`; a test puts its own).
    make_owner_account: Callable[[Settings, dict[str, Any]], Any] | None = None
    #: The helper (docs/36 section 3): what the admin pages ask of the computer; `None` when this install has none.
    helper: HelperClient | None = None
    #: The server's own gateways and addresses, read once at start (`netaddr.read_own_network`); `None` when it cannot read them. What lets the server tell a visitor from the
    #: gateway that hides one (P3-34): without it no direct visitor is proved to be at home.
    own_network: netaddr.OwnNetwork | None = None


def services(request: Request) -> Services:
    return request.app.state.services  # type: ignore[no-any-return]


# ------------------------------------------------------------------------------------------------ who is asking


def get_principal(request: Request) -> Principal:
    svc = services(request)
    headers = dict(request.headers.items())
    token = bearer_token(headers.get("authorization"))
    # Signing in is a READ. The database is in WAL mode so that readers never wait for the writer; a sign-in that wrote (or merely took the write lock)
    # on every request made every call of every phone queue behind every other (measured: B-10, 20 phones, p95 of a plain read 2.5 s).
    if token is not None:
        with svc.db.read() as conn:
            row = conn.execute(
                "SELECT d.id AS device, d.kind AS kind, d.created_at AS created, d.last_seen AS seen, p.id AS person, p.navidrome_user AS user,"
                " p.role AS role, p.locked AS locked"
                " FROM device d JOIN person p ON p.id = d.person WHERE d.token_hash = ? AND d.revoked_at IS NULL",
                (hash_token(token),),
            ).fetchone()
        if row is None or row["locked"]:
            raise ApiError("unauthorized", "This device is not signed in any more. Sign in again.")
        if row["kind"] == "web" and web_session_over(row["created"], row["seen"], now_ms()):
            raise ApiError("unauthorized", "This browser was signed out after a while. Sign in again.")
        _note_device_seen(svc, row["device"], row["seen"])
        return Principal(row["person"], row["user"], row["role"], row["device"])

    creds = subsonic_credentials(dict(request.query_params.items()), headers)
    if creds is None:
        raise ApiError("unauthorized")
    user, subsonic, salt = creds
    check_music_login(request, user, subsonic, salt)
    with svc.db.read() as conn:
        person = conn.execute("SELECT * FROM person WHERE navidrome_user = ?", (user,)).fetchone()
    if person is None:
        # A person seen for the first time. The music server is asked OUTSIDE any transaction: a slow answer (8 s at worst) must not hold the
        # write lock, which would stop every other phone for as long (measured: B-18). `ensure_person` looks again inside its own transaction.
        admin = svc.verifier.is_admin(user, subsonic, salt)
        with svc.db.tx() as conn:
            person = library.ensure_person(conn, user, admin=admin)
    if person["locked"]:
        raise ApiError("forbidden", "This account is locked.")
    device = request.headers.get("x-encore-device")
    return Principal(person["id"], user, person["role"], device if device and is_id(device, "dv") else None)


#: A device's "last seen" is written at most this often.
LAST_SEEN_EVERY_MS = 60_000


def _note_device_seen(svc: Services, device: str, seen: int | None) -> None:
    """Writes when a device was last seen, at most once a minute. A best effort: being unable to write it (the database is busy) never refuses the
    request that is being signed in."""
    now = now_ms()
    if seen is not None and seen >= now - LAST_SEEN_EVERY_MS:
        return
    try:
        with svc.db.tx() as conn:
            conn.execute(
                "UPDATE device SET last_seen = ? WHERE id = ? AND (last_seen IS NULL OR last_seen < ?)",
                (now, device, now - LAST_SEEN_EVERY_MS),
            )
    except sqlite3.OperationalError:
        log.debug("could not note that a device was seen: the database is busy")


def check_music_login(request: Request, user: str, subsonic: str, salt: str) -> None:
    """The one place a music-server login (`u`, `t`, `s`) is checked, for the Encore API and for the Subsonic API that is open to the internet
    (AUDIT B12b: it used to be a second copy of nothing, i.e. no check at all). Raises an `ApiError` to refuse.

    Not a login the music server has already vouched for: a guesser is slowed before the music server is asked, a locked account says so
    whatever the password (so its answer never confirms a right one), and a wrong answer is counted (AUDIT B1, B2). A wrong answer is logged
    with the address it was counted against, never with the token; that is at most thirty lines an address a minute, because a refused guess is
    not counted again."""
    svc = services(request)
    known = getattr(svc.verifier, "known_good", None)
    if known is not None and known(user, subsonic, salt):
        return
    address = client_address(request)
    guard = LoginGuard(limiter_of(request))
    # A device the server already knows (a login the music server accepted within the day) is not refused by the guess limits; the music server still checks it just below.
    vouched = getattr(svc.verifier, "vouched", None)
    with guard.begin(
        user, address, vouched=bool(callable(vouched) and vouched(user, subsonic, salt))
    ):  # a slot while the music server is asked (P3-34 slice 2d)
        _refuse_locked(svc, user)
        if not svc.verifier.verify(user, subsonic, salt):
            guard.failed(user, address)
            log.info("a wrong music-server login was refused: name %r, counted against address %s", user, address)
            raise ApiError("unauthorized", "The music server did not accept that login.")


async def authorize_public_subsonic(request: Request, login: subsonic_guard.HomeLogin | None) -> None:
    """A call to the Subsonic API that comes from the internet is signed in like any other call to this server (AUDIT B12b). Only the token login
    (`u`, `t`, `s`) is understood: a plain password (`p=`, `p=enc:`) or an API key is refused, because a password a stranger can try without limit
    is exactly what this guard exists to stop (docs/21: Subsonic apps that send only `p=` cannot sign in through the public address).

    [login] is the login the gateway read from the call the way the MUSIC SERVER reads it (the address and the form body; never an `X-Encore-*` header, which the music server ignores; a name given
    twice already refused): the login that is checked here is the one the music server will check, never a decoy (P3-34 slice 2b review)."""
    # Only the shapes the apps of this server make (the music server takes any, and the home door counts any): a name of letters and digits, a 32-hex token, a salt of 4 to 64 letters and digits.
    if login is None or subsonic_credentials({"u": login.user, "t": login.token, "s": login.salt}, {}) is None:
        raise ApiError(
            "unauthorized", "Sign in with a token login (u, t and s). A plain password is not accepted from the internet."
        )
    await run_in_threadpool(
        _check_public_subsonic, request, login.user, login.token.lower(), login.salt
    )  # asking the music server is a blocking call


def _check_public_subsonic(request: Request, user: str, subsonic: str, salt: str) -> None:
    # A remembered yes must never open a locked account: the Encore API looks the person up after the check, this door has no such later step.
    _refuse_locked(services(request), user)
    check_music_login(request, user, subsonic, salt)


def _refuse_locked(svc: Services, user: str) -> None:
    """A locked account is refused before its password is looked at, so the answer never tells anybody whether a guess was right."""
    with svc.db.read() as conn:
        row = conn.execute("SELECT locked FROM person WHERE navidrome_user = ?", (user,)).fetchone()
    if row is not None and row["locked"]:
        raise ApiError("forbidden", "This account is locked. Ask the owner of this server to unlock it.")


async def json_body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except ValueError:
        raise ApiError("validation", "The request body must be JSON.") from None
    if not isinstance(data, dict):
        raise ApiError("validation", "The request body must be a JSON object.")
    return data


async def optional_body(request: Request) -> dict[str, Any]:
    """The JSON body when there is one (a like needs none); anything else is no body."""
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _server_time() -> int:
    return now_ms()


def _ok(payload: dict[str, Any] | None = None, status: int = 200) -> JSONResponse:
    return JSONResponse({**(payload or {}), "serverTime": _server_time()}, status_code=status)


def _youtube_status(youtube: YoutubeSource | None) -> dict[str, Any]:
    """`{state: off|ok|resting, resumesInSec}`: whether YouTube is holding this server back, and for how long (the same in `info` and in the keep progress)."""
    if youtube is not None and hasattr(youtube, "status"):
        return youtube.status()
    return {"state": "off", "resumesInSec": 0}


def client_address(request: Request) -> str:
    """Who is asking, for every limit: the address of the connection; and only when that connection is a proxy of ours (this machine, the home or
    Docker network, Tailscale, or one the owner listed) the address it says it forwarded: the right-most one that is not itself a proxy, never the
    client-written first one (AUDIT B11, `netaddr`)."""
    peer = request.client.host if request.client else ""
    extra = netaddr.networks(services(request).settings.trusted_proxies)
    return netaddr.client_address(peer, request.headers.get("x-forwarded-for"), extra)


def _by_the_away_address(request: Request) -> bool:
    """Did the request come in under the away address (the name the internet reaches this server by)? Then the visitor is the internet, whatever address the connection shows."""
    away = services(request).settings.away_url
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower() if "]" not in (request.headers.get("host") or "") else ""
    return bool(away and host and host == (urlparse(away).hostname or "").lower())


def is_public_request(request: Request) -> bool:
    """Did this request come in from the public internet (through the away address, or from an address that is not ours)? The gateway lets such a
    request reach only the Subsonic API of the music server (AUDIT B12)."""
    if _by_the_away_address(request):
        return True
    return netaddr.is_public(client_address(request))


def music_web_page_open(request: Request) -> bool:
    """May this visitor open the music server's own web page, sign-in and `/api` through the gateway? (P3-34, audit B-56.) Only when the Host switched `music-web-page` on AND the
    server can PROVE the visitor is on the home network (`netaddr.provably_home`): a private address is not proof, because where Docker hides the visitor's address everybody
    arrives from the network's own gateway. Never for a request under the away address."""
    svc = services(request)
    if not svc.settings.music_web_page or _by_the_away_address(request):
        return False
    peer = request.client.host if request.client else None
    return netaddr.provably_home(
        peer, request.headers.get("x-forwarded-for"), svc.own_network, netaddr.networks(svc.settings.trusted_proxies)
    )


class HomeAttempt:
    """What [HomeLoginGuard.begin] hands the gateway: the refusal to answer with (or `None`), and the slot the check holds, given back by [release] once the music server has answered."""

    def __init__(self, refusal: tuple[int, dict[str, str], bytes] | None, attempt: Attempt | None) -> None:
        self.refusal = refusal
        self._attempt = attempt

    def release(self) -> None:
        if self._attempt is not None:
            self._attempt.release()


class HomeLoginGuard:
    """Wrong logins at HOME on `/rest`, counted from the music server's own answer (P3-34 slice 2b, audit B-56; `subsonic_guard.py` is the pure half).

    At home the music server checks a login, not this one, so the gateway passes the call on; this is what it asks of the guard around it. BEFORE: a call that carries a login (a token, `p=`,
    `p=enc:`, in the address or in a form body) is refused, in the format the app asked for, when its name, address or account has had too many wrong answers, unless it is a device this
    server already knows (a login the music server accepted within the day: the memory of `NavidromeVerifier.vouched`, which this renews and drops from what the gateway SEES). AFTER: a small,
    sized json or xml answer with a login-refused code is a wrong guess and is counted; anything else that is a 200 or a 206 is the music server accepting the login."""

    def begin(self, request: Request, login: subsonic_guard.HomeLogin) -> HomeAttempt:
        """The refusal to answer instead of passing the call on (a name, address or account with too many wrong answers, or too many checks of it under way at once), or the slot the check holds
        while the music server answers (P3-34 slice 2d): the gateway gives it back with `release`, on every way out."""
        svc = services(request)
        vouched = getattr(svc.verifier, "vouched", None)
        known = bool(callable(vouched) and vouched(login.user, login.token, login.salt))
        try:
            attempt = LoginGuard(limiter_of(request)).begin(login.user, client_address(request), vouched=known)
        except ApiError as refusal:
            fmt, callback = subsonic_guard.format_of(dict(request.query_params.items()))
            body, kind = subsonic_guard.refusal_body(fmt, callback, "Too many wrong tries. Wait a moment and try again.")
            wait_s = max(1, -(-(refusal.retry_after_ms or 1000) // 1000))
            return HomeAttempt((429, {"Content-Type": kind, "Retry-After": str(wait_s), "Cache-Control": "no-store"}, body), None)
        return HomeAttempt(None, attempt)

    def settle(self, request: Request, login: subsonic_guard.HomeLogin, *, refused: bool) -> None:
        svc = services(request)
        if refused:
            address = client_address(request)
            LoginGuard(limiter_of(request)).failed(login.user, address)
            log.info(
                "a wrong music-server login at the home door was counted: name %r, counted against address %s",
                login.user,
                address,
            )
            drop = getattr(svc.verifier, "drop_vouch", None)
            if callable(drop):
                drop(login.user, login.token, login.salt)
            return
        note = getattr(svc.verifier, "note_accepted", None)
        if callable(note):
            note(login.user, login.token, login.salt)


def accounts_of(request: Request) -> Accounts:
    service = services(request).accounts
    assert service is not None
    return service


def notifications_of(request: Request) -> Notifications:
    service = services(request).notifications
    assert service is not None
    return service


def limiter_of(request: Request) -> Limiter:
    limiter = services(request).limiter
    assert limiter is not None
    return limiter


def refuse_public(request: Request) -> None:
    """A dependency of every admin route and page (docs/36 section 2, `15` section 4: "home network only; never on the public address"): a request that came in
    from the internet gets the very answer an unknown route of ours gets, so it learns nothing about what is here. Declared BEFORE the sign-in dependency, so a
    stranger without a token is told "not found", not "sign in"."""
    if is_public_request(request):
        raise ApiError("not_found")


def require_owner(p: Principal) -> None:
    if p.role != "owner":
        raise ApiError("forbidden", "Only the owner of this server can do that.")


def _keep_state(svc: Services, conn: Any, ref_id: str, *, host: bool = False) -> dict[str, Any]:
    """How the server is getting one song. The `reason` is a sentence for the person who asks (`keeper/failures.py`): the Host reads the cause, anybody
    else the plain fact, and never the raw text the keeper stored (it can name an exception, a file or a folder)."""
    linked = conn.execute("SELECT 1 FROM song_file WHERE ref = ? AND navidrome_song_id IS NOT NULL LIMIT 1", (ref_id,)).fetchone()
    if linked is not None:
        return {"state": "kept"}
    if svc.scheduler is None or not svc.scheduler.handles("keep"):
        return {"state": "unavailable", "reason": "This server does not keep songs."}
    item = svc.scheduler.state_of("keep", ref_id)
    if item is None or item["state"] in ("cancelled", "done"):
        return {"state": "none"}
    state = {"queued": "queued", "running": "keeping", "failed": "failed"}.get(str(item["state"]), "queued")
    error = str(item["error"]) if item["error"] else None
    reason = describe_failure(error, host=host).reason if state == "failed" else describe_wait(error, host=host)
    return {"state": state, **({"reason": reason} if reason else {})}


_COVER_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def _changed(svc: Services, p: Principal, conn_cursor: int) -> None:
    svc.hub.publish(p.person_id, {"type": "library.changed", "cursor": str(conn_cursor)}, except_device=p.device_id)


def want_kept(svc: Services, conn: sqlite3.Connection, person: str, ref_ids: list[str]) -> None:
    _want_kept(svc.scheduler, conn, person, ref_ids)
