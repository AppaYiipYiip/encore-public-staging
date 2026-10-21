"""Whose sign-in is this? The name and email of the Google account behind a saved YouTube login (docs/50).

A card in the admin website says which account it is, so with several accounts the owner knows which one did how many songs. The
answer is asked of Google's own account list (`accounts.google.com/ListAccounts`, the call a browser makes to learn which accounts
are signed in), with the saved sign-in as the cookies, once when an account is added. The picture and the account id it also
returns are ignored and never kept.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path

log = logging.getLogger("encore_fetch.identity")

URL = "https://accounts.google.com/ListAccounts?gpsia=1&source=ChromiumBrowser&json=standard"
_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def parse_accounts(raw: str) -> dict | None:
    """The first signed-in account in Google's answer: `{"name", "email"}`, or `None` when the answer is not what is expected."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None

    def entries(node):
        if isinstance(node, list):
            strings = [item for item in node if isinstance(item, str)]
            if node and node[0] == "gaia.l.a" and any("@" in s for s in strings):
                yield strings
            for item in node:
                yield from entries(item)

    for strings in entries(data):
        email = next((s for s in strings[1:] if "@" in s and " " not in s), "")
        names = [s for s in strings[1:] if s != email and not s.startswith("http") and not s.isdigit()]
        if email:
            return {"name": names[0][:60] if names else "", "email": email[:120]}
    return None


def account_identity(path: Path, *, timeout: float = 15.0) -> dict | None:
    """The name and email of the account whose sign-in is saved at [path], or `None` (offline, or Google changed its answer)."""
    try:
        from yt_dlp.cookies import YoutubeDLCookieJar
    except ImportError:  # pragma: no cover - yt-dlp is installed with the service
        return None
    try:
        jar = YoutubeDLCookieJar(str(path))
        jar.load(ignore_discard=True, ignore_expires=True)
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        request = urllib.request.Request(URL, data=b"", headers={"User-Agent": _AGENT, "Origin": "https://accounts.google.com"})
        with opener.open(request, timeout=timeout) as response:  # noqa: S310 - Google's own address
            return parse_accounts(response.read(200_000).decode("utf-8", "replace"))
    except Exception as error:  # noqa: BLE001 - not knowing the name must never stop an account from being kept
        log.info("could not ask Google whose sign-in this is (%s)", type(error).__name__)
        return None
