"""The admin site's files (docs/36 section 2): a few static pages and scripts shipped in the image, served with the headers of a page that holds a sign-in.

No build step, no framework and no outside request (no font service, no analytics): a server on a computer with the internet unplugged serves the same pages. The
policy is strict on purpose: **no inline script, no inline style, no `eval`** (a test fails on any of them in `web/`), nothing the page loads comes from anywhere
but this server, the page cannot be put in a frame, and it sends no referrer (the setup page's address carries a code). A name or a word that reaches the page
is written into it as text, never as markup. This policy belongs to the admin site: the web player (P6-02) is the app built for the browser and has its own.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent / "web"

#: One page per address, named by the route that serves it.
PAGES = {"admin": "admin.html"}

#: What a script, a stylesheet or a font may be asked for as (never a page, never anything else in the folder).
ASSET_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
}

#: A path under /encore/web/: names of letters, digits, dots, dashes and underscores, one folder deep at most (the fonts).
ASSET_PATH = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}(/[A-Za-z0-9_-][A-Za-z0-9._-]{0,63})?$")

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)

#: Sent with every page and file of the site.
COMMON_HEADERS = {
    "Content-Security-Policy": CSP,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}
#: A page is never kept; a script or a style may be kept but is asked about every time (the files are small, and a new version of the server must show at once).
PAGE_HEADERS = {**COMMON_HEADERS, "Cache-Control": "no-store"}
ASSET_HEADERS = {**COMMON_HEADERS, "Cache-Control": "no-cache"}


def page(name: str) -> bytes | None:
    """The bytes of a page of the site, or None."""
    file = PAGES.get(name)
    return (WEB_DIR / file).read_bytes() if file is not None else None


def asset(path: str) -> tuple[bytes, str] | None:
    """The bytes and the content type of a script, a stylesheet or a font, or None for anything else: a path that is not of the shape above, a type that is not
    in the list, a file that is not there, or a name that would leave the folder."""
    if ASSET_PATH.fullmatch(path) is None or ".." in path:
        return None
    kind = ASSET_TYPES.get(Path(path).suffix.lower())
    if kind is None:
        return None
    target = (WEB_DIR / path).resolve()
    if not target.is_file() or WEB_DIR not in target.parents:
        return None
    return target.read_bytes(), kind
