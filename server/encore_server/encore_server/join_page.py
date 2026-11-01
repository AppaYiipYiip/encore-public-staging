"""The page an invitation link opens in a browser (docs/design W-05, decision D-39).

A friend taps `https://<server>/encore/join/<code>` in a message. On Android 12 and later the browser opens it (a link to an arbitrary self-hosted
address cannot be verified for the app), and before this page existed it showed the music server's own page or a 404: a dead end for somebody who
only has the link. So the server answers it with a small page that says what the link is and what to do.

**Two pages, no more.** A page cannot know whether the app is installed, so one valid page says both: press "Open in Encore", or get the app and come
back. And **one identical page, with one status, for every dead code** (used, expired, revoked, never existed, not even shaped like a code): it names
nothing, so it tells a stranger nothing about which kind of dead it is.

**The page is public on the internet** (the guided way in is Tailscale Funnel), so it is built to leak nothing and run nothing: every name is escaped, it
has no script, no font, no image (a cover would show the household's music to anybody holding the link), the code never leaves through a referrer, and
nothing caches it.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

#: The Android package the "Open in Encore" link names: an explicit package opens the app without a verified link in Chrome and its relatives.
APP_PACKAGE = "app.encore.player"

#: Only the shape of a code is checked here (letters, digits, dashes, a sane length); whether it is a live invitation is the invitation check's call.
CODE_SHAPE = re.compile(r"^[A-Za-z0-9-]{4,40}$")

#: The server key a link carries (`?id=`), so the phone that opens it can tell the server from anything else answering at that address.
KEY_SHAPE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

#: A host as a `Host` header carries it: a name or an address, an optional port, or a bracketed IPv6 address.
HOST_SHAPE = re.compile(r"^(?:[A-Za-z0-9.-]{1,253}|\[[0-9A-Fa-f:.]{2,45}\])(?::[0-9]{1,5})?$")

#: What the owner may set as the place to get the app: an http(s) address, nothing that could break out of an attribute.
APP_URL_SHAPE = re.compile(r"^https?://[^\s\"'<>`\\]{1,300}$")

#: Sent with every answer of this page, dead or alive: the code is in the address, so it must never travel in a referrer, a cache or a search index.
HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
}

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_STYLE = """
:root{color-scheme:light dark;--bg:#f7f8f7;--fg:#141816;--muted:#4c5651;--line:#dfe4e1;--accent:#07703f;--ink:#fff}
@media(prefers-color-scheme:dark){:root{--bg:#0e1110;--fg:#f1f4f2;--muted:#a7b1ab;--line:#2a302d;--accent:#19e68c;--ink:#05140d}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:30rem;margin:0 auto;padding:2.5rem 1.25rem 3rem}
h1{font-size:.8rem;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);margin:0 0 1.5rem}
h2{font-size:1.6rem;line-height:1.2;margin:0 0 .5rem}
h3{font-size:1rem;margin:2rem 0 .5rem}
p{margin:0 0 1rem}
.muted{color:var(--muted)}
.btn{display:inline-block;box-sizing:border-box;min-height:48px;padding:.8rem 1.2rem;border-radius:.6rem;background:var(--accent);color:var(--ink);font-weight:600;text-decoration:none}
.btn.quiet{background:transparent;color:var(--accent);border:1px solid var(--accent)}
ol{padding-left:1.3rem;margin:0 0 1rem}
li{margin:.3rem 0}
.box{font:.85rem/1.4 ui-monospace,Menlo,Consolas,monospace;word-break:break-all;padding:.75rem;border:1px solid var(--line);border-radius:.5rem;user-select:all}
"""


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head><body><main><h1>Encore</h1>{body}</main></body></html>"
    )


#: The page for every dead code. A constant, so it is byte for byte the same whatever was asked: it names no server, no person and no code.
DEAD_PAGE = _page(
    "This invitation did not open",
    "<h2>This invitation did not open</h2><p>That invitation is not valid any more. Ask for a new one.</p>",
)


def public_origin(host: str | None, forwarded_proto: str | None, scheme: str) -> tuple[str, str] | None:
    """The `(scheme, host)` this request came in through, as the visitor's own browser addressed it, or `None` when either does not look right.

    A server behind a tunnel sees plain http while the visitor used https, so the proxy's word counts for the scheme; the page only ever writes it
    back to the same visitor, and only http or https is accepted.
    """
    proto = (forwarded_proto or "").split(",")[0].strip().lower() or scheme.lower()
    if proto not in ("http", "https") or not host or not HOST_SHAPE.match(host):
        return None
    return proto, host


def expiry_text(expires_at_ms: object) -> str | None:
    """`5 November 2026` (UTC), or `None` when the invitation has no known end."""
    if not isinstance(expires_at_ms, (int, float)) or isinstance(expires_at_ms, bool) or expires_at_ms <= 0:
        return None
    try:
        moment = datetime.fromtimestamp(expires_at_ms / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year}"


def valid_page(
    *,
    server_name: str,
    invited_by: str | None,
    code: str,
    origin: tuple[str, str] | None,
    key: str | None,
    expires_at_ms: object,
    app_url: str,
) -> str:
    """The page for a live invitation. Every value that came from a person, a setting or the request is escaped here, once."""
    name = html.escape(server_name or "this server")
    who = html.escape(invited_by) if invited_by else None
    lead = (
        f"{who} invited you to listen on {name}. Encore is the app you listen with."
        if who
        else f"You are invited to listen on {name}. Encore is the app you listen with."
    )
    suffix = f"?id={key}" if key and KEY_SHAPE.match(key) else ""
    path = f"/encore/join/{code}{suffix}"
    parts = [f"<h2>{name}</h2>"]
    if who:
        parts.append(f'<p class="muted">Invited by {who}</p>')
    parts.append(f"<p>{lead}</p>")
    if origin is not None:
        proto, host = origin
        intent = f"intent://{host}{path}#Intent;scheme={proto};package={APP_PACKAGE};end"
        parts.append(f'<p><a class="btn" href="{html.escape(intent, quote=True)}">Open in Encore</a></p>')
    getting = (
        f'Get Encore: <a href="{html.escape(app_url, quote=True)}">download the app</a>.'
        if app_url and APP_URL_SHAPE.match(app_url)
        else f"Ask {who or 'the person who invited you'} for the Encore app."
    )
    parts.append(
        f"<h3>Do not have Encore yet?</h3><ol><li>{getting}</li><li>Come back to this page and press Open in Encore.</li></ol>"
    )
    if origin is not None:
        link = f"{origin[0]}://{origin[1]}{path}"
        parts.append(
            f'<p>Or copy this link and paste it in Encore, on its first screen:</p><p class="box">{html.escape(link)}</p>'
        )
    until = expiry_text(expires_at_ms)
    if until:
        parts.append(f'<p class="muted">This invitation works until {html.escape(until)}.</p>')
    return _page(f"Join {server_name or 'this server'}", "".join(parts))
