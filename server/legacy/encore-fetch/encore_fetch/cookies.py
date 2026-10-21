"""A YouTube login for the downloads, optional.

YouTube lets a visitor without a login fetch about 300 videos an hour from one address and refuses beyond that ("Sign in
to confirm you're not a bot"); an account gets about 2,000 an hour, may fetch the age-restricted songs a visitor cannot,
and lets private playlists and the YouTube Music liked songs be read (yt-dlp wiki; ADR-103). A program cannot sign in to
Google with a password (2-step verification, device checks), so the login is what a browser already has: its cookies,
as a Netscape `cookies.txt`. The owner puts that file in the app (Settings > Your server > YouTube sign-in) or runs
`server/migrate/owner-server/s10_youtube_login.sh`; the service keeps it as `youtube-cookies.txt` in its work folder.

[cookie_args] is asked at every run, so a file that appears (or goes) is used by the next song without a restart.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

#: Cookies that say "this is a signed-in session".
_LOGIN = ("SID", "__Secure-3PSID", "__Secure-1PSID", "LOGIN_INFO")
MAX_BYTES = 400_000


def cookie_args(path: str | None) -> list[str]:
    """`--cookies <file>` when there is a cookies file *now*."""
    if not path:
        return []
    try:
        if Path(path).stat().st_size > 0:
            return ["--cookies", path]
    except OSError:
        pass
    return []


class CookieProblem(Exception):
    """Why a file cannot be used, in a sentence for the person."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Report:
    rows: int
    login_cookies: int
    #: When the first login cookie runs out (seconds since 1970), if it says.
    expires: int | None


def check_text(text: str, *, now: float | None = None) -> Report:
    """Raises [CookieProblem] unless [text] is a Netscape cookies file of a signed-in YouTube or Google session."""
    if len(text) > MAX_BYTES:
        raise CookieProblem("That file is too big to be a cookies file.")
    now = time.time() if now is None else now
    rows, domains, login, soonest = 0, set(), 0, None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue  # a comment (the file's first line)
        parts = line.removeprefix("#HttpOnly_").split("\t")
        if len(parts) != 7:
            raise CookieProblem("That is not a cookies.txt file (every line must have 7 fields separated by tabs). "
                                "Export it from the browser with a cookies exporter, in the Netscape format.")
        rows += 1
        domain, expiry, name = parts[0].lower(), parts[4], parts[5]
        domains.add(domain.lstrip("."))
        if name in _LOGIN and ("youtube" in domain or "google" in domain):
            login += 1
            if expiry.isdigit() and int(expiry) > 0:
                soonest = int(expiry) if soonest is None else min(soonest, int(expiry))
    if not rows:
        raise CookieProblem("That file has no cookies in it.")
    if not any(d.endswith("youtube.com") or d.endswith("google.com") for d in domains):
        raise CookieProblem("There are no youtube.com cookies in that file. Export it while you are on youtube.com.")
    if not login:
        raise CookieProblem("These cookies are not signed in (there is no login cookie). Sign in to YouTube in the "
                            "browser first, then export.")
    if soonest is not None and soonest < now:
        raise CookieProblem("The login in that file has already run out. Export it again.")
    return Report(rows, login, soonest)


class Lease:
    """The cookies one yt-dlp run uses, and a way to say how the run went (so an account YouTube refuses can rest while
    the others carry on: accounts.py). A run with no account has no cookies and nobody to tell."""

    def __init__(self, args: list[str] | None = None, account_id: str | None = None,
                 report: Callable[[str, str], None] | None = None) -> None:
        self.args = list(args or [])
        self.account_id = account_id
        self._report = report

    def done(self, outcome: str) -> None:
        """`"blocked"` when YouTube refused the run; anything else when YouTube answered normally."""
        if self._report is not None and self.account_id is not None:
            self._report(self.account_id, outcome)


class StaticSource:
    """One cookies file, looked at at every run (a file that appears or goes is used by the next song)."""

    def __init__(self, path: str | None) -> None:
        self._path = path

    def lease(self, count: bool = True) -> Lease:
        return Lease(cookie_args(self._path))


def as_source(cookies: "str | None | object"):
    """A cookies path (or nothing) becomes a source; a source (accounts.py) stays as it is."""
    if cookies is None or isinstance(cookies, str):
        return StaticSource(cookies)
    return cookies


def status(path: str | None) -> dict:
    """What the owner is told about the login now."""
    out: dict = {"signedIn": False}
    if not path:
        return out
    try:
        info = Path(path).stat()
        if info.st_size <= 0:
            return out
        report = check_text(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, CookieProblem):
        return out
    out.update(signedIn=True, loginCookies=report.login_cookies, changed=int(info.st_mtime))
    if report.expires:
        out["expires"] = report.expires
    return out


def install(path: str, text: str, *, now: float | None = None) -> Report:
    """Checks [text] and keeps it as the login (owner-only file, replaced in one step)."""
    report = check_text(text, now=now)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(tmp, target)
    return report


def remove(path: str) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
