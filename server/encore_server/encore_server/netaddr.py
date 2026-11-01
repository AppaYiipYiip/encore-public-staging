"""Who is asking, and is it the public internet (AUDIT B11 and B12).

Every limit this server applies is keyed on an address, so the address has to be the connection's, not whatever the client writes. A tunnel or a
proxy in front of the server (Tailscale Funnel, the Docker network) connects from a private address and says who it forwarded in `X-Forwarded-For`:

* that header is believed **only when the connection itself comes from a proxy** (a loopback, private, link-local or Tailscale address, or one the
  owner listed in `ENCORE_TRUSTED_PROXIES`); from anybody else it is ignored, so a stranger cannot pick the address that is counted against them;
* a proxy *appends* the address it saw to whatever the client already sent, so the value that counts is the **right-most one that is not itself a
  proxy**; the first value is the client's own and is never used;
* a value that is not an address ends the search: nothing is believed beyond it.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
Address = ipaddress.IPv4Address | ipaddress.IPv6Address

#: What counts as "one of ours" without being told: this machine, the home network, the Docker networks, link-local, a Tailscale address.
PRIVATE: tuple[Network, ...] = tuple(
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",
        "::1/128",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
        "fc00::/7",
        "fe80::/10",
    )
)


def _address(text: str | None) -> Address | None:
    if not text:
        return None
    text = text.strip()
    if text.startswith("["):  # `[::1]:4533`
        text = text[1 : text.find("]")] if "]" in text else text[1:]
    elif text.count(":") == 1:  # `1.2.3.4:5678`
        text = text.split(":", 1)[0]
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def networks(extra: Iterable[str]) -> tuple[Network, ...]:
    """The owner's own list of proxies (`ENCORE_TRUSTED_PROXIES`), as networks; an entry that is not one is left out."""
    found: list[Network] = []
    for entry in extra:
        try:
            found.append(ipaddress.ip_network(entry.strip(), strict=False))
        except ValueError:
            continue
    return tuple(found)


def is_proxy(address: str | None, extra: tuple[Network, ...] = ()) -> bool:
    found = _address(address)
    return found is not None and any(found in net for net in (*PRIVATE, *extra))


def is_public(address: str | None) -> bool:
    """A real internet address: not this machine, not the home network, not the Docker network, not Tailscale's, and not a made-up string."""
    found = _address(address)
    return found is not None and not any(found in net for net in PRIVATE)


def client_address(peer: str, forwarded_for: str | None, extra: tuple[Network, ...] = ()) -> str:
    """The address to count a request against."""
    if not is_proxy(peer, extra):
        return peer
    chain = [hop.strip() for hop in (forwarded_for or "").split(",") if hop.strip()]
    for hop in reversed(chain):
        found = _address(hop)
        if found is None:
            return peer  # not an address: nothing further left is believed
        if not is_proxy(str(found), extra):
            return str(found)
    return peer
