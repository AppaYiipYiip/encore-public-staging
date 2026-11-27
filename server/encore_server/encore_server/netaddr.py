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
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

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


# ---------------------------------------------------------------------------------------------------------------------------- "provably on the home network"

#: The only ranges that can be PROVED to be the home network (P3-34, audit B-56): the three private ranges of RFC 1918. Not loopback (this machine), not link-local, not
#: Tailscale's range (a tailnet can be shared with other people), not IPv6 (an address the server cannot read the home network of).
HOME_LAN: tuple[Network, ...] = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


@dataclass(frozen=True)
class OwnNetwork:
    """What the server knows of its own place on the network: the gateways its traffic leaves by and the addresses it has itself. Where the visitor's address is hidden
    (Docker Desktop, rootless Docker, Podman, some NAS stacks) every visitor arrives as one of these, and none of them is a visitor."""

    gateways: frozenset[Address]
    addresses: frozenset[Address]


def default_gateways(route_table: str | None) -> frozenset[Address] | None:
    """The gateways of the default routes in the text of `/proc/net/route` (`Iface Destination Gateway Flags RefCnt Use Metric Mask ...`, addresses as little-endian hex).
    `None` when the text is not a route table at all (not an empty one: a table with no default route is a network that goes nowhere, and has no gateway)."""
    if not route_table:
        return None
    lines = [line.split() for line in route_table.splitlines() if line.strip()]
    if not lines or lines[0][:3] != ["Iface", "Destination", "Gateway"]:
        return None
    found: set[Address] = set()
    rows = 0
    for fields in lines[1:]:
        if len(fields) < 8:
            continue
        try:
            destination, gateway, flags, mask = int(fields[1], 16), fields[2], int(fields[3], 16), int(fields[7], 16)
            address = ipaddress.IPv4Address(int.from_bytes(bytes.fromhex(gateway), "little"))
        except ValueError:
            continue
        rows += 1
        if destination == 0 and mask == 0 and flags & 0x3 == 0x3:  # the default route, up, through a gateway
            found.add(address)
    return frozenset(found) if rows else None


def _own_addresses() -> set[str]:
    try:
        return {str(info[4][0]) for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        return set()


def read_own_network(
    route_file: Path | str = "/proc/net/route", own_addresses: Callable[[], Iterable[str]] = _own_addresses
) -> OwnNetwork | None:
    """The server's own gateways and addresses, read once at start. `None` when the route table cannot be read (not Linux, not a container, no permission): the server then
    cannot tell a visitor from the gateway that hides one, and the answer for every direct visitor is no (fail shut)."""
    try:
        text = Path(route_file).read_text(encoding="utf-8")
    except OSError:
        return None
    gateways = default_gateways(text)
    if gateways is None:
        return None
    addresses: set[Address] = {ipaddress.ip_address("127.0.0.1")}
    for entry in own_addresses():
        found = _address(entry)
        if found is not None:
            addresses.add(found)
    return OwnNetwork(gateways=gateways, addresses=frozenset(addresses))


def _home_lan(address: Address, own: OwnNetwork) -> bool:
    return (
        isinstance(address, ipaddress.IPv4Address)
        and any(address in net for net in HOME_LAN)
        and address not in own.gateways
        and address not in own.addresses
    )


def provably_home(peer: str | None, forwarded_for: str | None, own: OwnNetwork | None, extra: tuple[Network, ...] = ()) -> bool:
    """Can the server PROVE this visitor is on the home network? (P3-34, audit B-56.) "A private address" is not proof: where Docker hides the visitor's address every
    connection arrives from the network's own gateway, which is private. So:

    * a **direct** visitor is home when its own connection comes from one of the three private ranges and is not the server's own gateway or address (loopback is this
      machine and no visitor); whatever it writes in `X-Forwarded-For` is ignored, in both directions;
    * what a client writes in `X-Forwarded-For` is read only when the connection comes from a **proxy the Host listed** (`ENCORE_TRUSTED_PROXIES`): the right-most address
      in it that is not itself a listed proxy is the visitor (a proxy appends what it saw; the first value is the client's own), and it must pass the same test;
    * a listed proxy that is the server's own gateway or own address proves nothing (every visitor arrives as the gateway where the address is hidden), and when the server cannot
      read its own network it cannot rule that out: no direct visitor and no listed proxy is believed (fail shut).

    Tailscale's range, link-local, IPv6 and public addresses are never proved. This is NOT [client_address], which believes the header from any private neighbour (right for
    counting guesses, wrong as proof of where somebody is)."""
    found = _address(peer)
    if found is None:
        return False
    if any(found in net for net in extra):
        # A listed proxy is believed about who it forwarded ONLY when it is a proxy of its own. Where the visitor's address is hidden, EVERY visitor arrives as the server's gateway:
        # listing that address (or the server's own) would let any visitor write `X-Forwarded-For: 192.168.1.50` and be home. Without its own network the server cannot rule that out.
        if own is None or found in own.gateways or found in own.addresses:
            return False
        visitor = None
        for hop in reversed([h.strip() for h in (forwarded_for or "").split(",") if h.strip()]):
            candidate = _address(hop)
            if candidate is None:
                return False  # not an address: nothing further left is believed
            if any(candidate in net for net in extra):
                continue
            visitor = candidate
            break
        return visitor is not None and _home_lan(visitor, own)
    return own is not None and _home_lan(found, own)
