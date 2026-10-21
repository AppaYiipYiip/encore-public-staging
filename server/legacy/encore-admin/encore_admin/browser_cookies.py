"""The sign-in a person made in the admin's browser window, read out of the browser's cookie file (docs/50 section 4).

The window is a Firefox in its own container. Firefox keeps its cookies in a plain SQLite file (`cookies.sqlite`), so nothing has to be
decrypted. While Firefox runs, its newest cookies are in the file's write-ahead log (`cookies.sqlite-wal`), not yet in the main file;
the three files are therefore handled together: written into a scratch folder and opened there, where SQLite replays the log. The
files themselves come out of the browser's container through Docker (docker_api.Docker.read_file), so the website needs no folder
shared with the host or with any other service, which is what lets it run the same on any system that runs Docker. Only YouTube and
Google cookies are kept from what is read; nothing is sent anywhere but the songs service, and nothing is shown.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

#: Cookies of these sites are the sign-in; nothing else in the profile is read out.
SITES = ("youtube.com", "google.com", "googlevideo.com", "ytimg.com", "youtube-nocookie.com")
#: The cookies that say "this is a signed-in session".
LOGIN = ("SID", "__Secure-3PSID", "__Secure-1PSID", "LOGIN_INFO")


def _seconds(value) -> int:
    """A cookie's expiry in seconds since 1970 (Firefox has stored it in seconds and, in some versions, in milliseconds; 0 is a
    session cookie)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number // 1000 if number > 10**12 else max(number, 0)


def session_text(database: bytes, wal: bytes | None = None, shm: bytes | None = None) -> str | None:
    """The browser's YouTube/Google cookies as a Netscape cookies.txt, from the bytes of `cookies.sqlite` (and, if there, its log
    and index). `None` when they cannot be read (not a database, no cookie table yet)."""
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "cookies.sqlite"
        copy.write_bytes(database)
        if wal:
            Path(scratch, "cookies.sqlite-wal").write_bytes(wal)
        if shm:
            Path(scratch, "cookies.sqlite-shm").write_bytes(shm)
        try:
            connection = sqlite3.connect(str(copy))
            try:
                rows = connection.execute(
                    "SELECT host, path, isSecure, expiry, name, value, isHttpOnly FROM moz_cookies").fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            return None
    lines = ["# Netscape HTTP Cookie File"]
    for host, path, secure, expiry, name, value, http_only in rows:
        domain = str(host)
        if not any(domain.lstrip(".").endswith(site) for site in SITES):
            continue
        if any(ch in f"{domain}{path}{name}{value}" for ch in "\t\r\n"):
            continue  # never write a cookie that could break the file's lines
        lines.append("\t".join([("#HttpOnly_" if http_only else "") + domain, "TRUE" if domain.startswith(".") else "FALSE", str(path),
                                "TRUE" if secure else "FALSE", str(_seconds(expiry)), str(name), str(value)]))
    return "\n".join(lines) + "\n"


def login_state(text: str | None) -> str:
    """`"youtube"` when YouTube itself has a login cookie (what downloads need), `"google"` when only google.com has one (the sign-in
    has just finished and the browser is still on its way to YouTube), `"none"` otherwise."""
    state = "none"
    for line in (text or "").splitlines():
        if not line.strip() or line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        parts = line.removeprefix("#HttpOnly_").split("\t")
        if len(parts) != 7 or parts[5] not in LOGIN:
            continue
        domain = parts[0].lower().lstrip(".")
        if domain.endswith("youtube.com"):
            return "youtube"
        if domain.endswith("google.com"):
            state = "google"
    return state
