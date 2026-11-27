"""`netaddr.provably_home` (P3-34 slice 1, audit B-56): which visitors the server can PROVE are on the home network.

Where Docker hides the visitor's address (Docker Desktop on Windows and macOS, rootless Docker, Podman, some NAS stacks) every connection arrives from the network's own
gateway, which is a private address. "A private address" is therefore no proof: the server's own gateways and its own addresses are never a visitor, and the address a
client writes in `X-Forwarded-For` is believed only from a proxy the Host LISTED (`ENCORE_TRUSTED_PROXIES`), never from a neighbour that merely looks private. The answer is
used by the gateway to decide who may open the music server's own web page, `/api` and sign-in (the Host's switch must also be on).

Decided, and tested: only IPv4 addresses of the three private ranges (RFC 1918) can be proved home; loopback, link-local, Tailscale's range, IPv6 and anything the server
cannot read about itself are not.
"""

from __future__ import annotations

import ipaddress

import pytest

from encore_server import netaddr
from encore_server.netaddr import OwnNetwork

# A Docker bridge as the server sees it from inside: it is 172.19.0.3, its gateway is 172.19.0.1 (what a visitor looks like where the address is hidden).
OWN = OwnNetwork(
    gateways=frozenset({ipaddress.ip_address("172.19.0.1")}),
    addresses=frozenset({ipaddress.ip_address("172.19.0.3"), ipaddress.ip_address("127.0.0.1")}),
)
LISTED = netaddr.networks(["172.19.0.9"])  # the Host's own Caddy, listed in ENCORE_TRUSTED_PROXIES


def home(
    peer: str | None, forwarded: str | None = None, own: OwnNetwork | None = OWN, listed: tuple[netaddr.Network, ...] = ()
) -> bool:
    return netaddr.provably_home(peer, forwarded, own, listed)


@pytest.mark.parametrize("peer", ["192.168.1.50", "10.0.0.7", "172.20.5.5", "172.31.255.254", "192.168.0.1"])
def test_a_visitor_on_a_private_home_range_that_is_not_the_servers_own_is_home(peer: str) -> None:
    assert home(peer) is True


def test_the_servers_own_gateway_is_never_a_visitor() -> None:
    """Where the address is hidden, every visitor, from the house or from the internet, arrives as this."""
    assert home("172.19.0.1") is False


def test_the_servers_own_address_is_never_a_visitor() -> None:
    """Rootless setups present a visitor as the container's own address."""
    assert home("172.19.0.3") is False


@pytest.mark.parametrize("peer", ["127.0.0.1", "127.5.5.5", "::1"])
def test_this_machine_is_not_a_visitor(peer: str) -> None:
    assert home(peer) is False


def test_a_bridge_gateway_that_writes_a_home_address_in_forwarded_for_is_still_no() -> None:
    """The forged header: a visitor from the internet, arriving through the hidden-address gateway, writes a LAN address."""
    assert home("172.19.0.1", "192.168.1.50") is False
    assert home("172.19.0.1", "10.0.0.5, 192.168.1.50") is False


def test_a_neighbour_that_looks_private_cannot_vouch_for_anybody_either() -> None:
    """Only a proxy the Host listed is believed about who it forwarded; a peer that is merely on the network says nothing for anybody else, in either direction."""
    assert home("192.168.1.77", "8.8.8.8") is True, "a visitor on the LAN is home by its own connection, whatever it writes"
    assert home("8.8.8.8", "192.168.1.50") is False, "a visitor from the internet is not made home by the address it writes"
    assert home("172.19.0.1", "192.168.1.50") is False, "nor the hidden-address gateway"
    assert home("172.19.0.5", "8.8.8.8") is True, (
        "another container of the Host's own stack is on the Host's own network: its own connection decides, not its header"
    )


def test_a_proxy_the_host_listed_is_believed_about_who_it_forwarded() -> None:
    assert home("172.19.0.9", "192.168.1.50", listed=LISTED) is True


def test_a_listed_proxy_forwarding_a_public_address_is_no() -> None:
    assert home("172.19.0.9", "8.8.8.8", listed=LISTED) is False
    assert home("172.19.0.9", "203.0.113.7", listed=LISTED) is False


def test_a_listed_proxy_that_forwards_nobody_is_no() -> None:
    assert home("172.19.0.9", None, listed=LISTED) is False
    assert home("172.19.0.9", "", listed=LISTED) is False
    assert home("172.19.0.9", "not-an-address", listed=LISTED) is False


def test_behind_a_listed_proxy_the_address_that_counts_is_the_one_the_proxy_saw() -> None:
    """A proxy APPENDS what it saw to what the client wrote: the right-most address that is not itself a listed proxy counts, never the first."""
    assert home("172.19.0.9", "192.168.1.9, 8.8.8.8", listed=LISTED) is False, (
        "the client wrote a LAN address first; the proxy saw a public one"
    )
    assert home("172.19.0.9", "8.8.8.8, 192.168.1.9", listed=LISTED) is True, (
        "the client wrote a public address; the proxy saw a LAN one"
    )
    assert home("172.19.0.9", "8.8.8.8, 192.168.1.9, 172.19.0.9", listed=LISTED) is True, (
        "a second listed proxy in the chain is stepped over"
    )


def test_a_listed_proxy_that_forwards_the_servers_own_gateway_is_no() -> None:
    assert home("172.19.0.9", "172.19.0.1", listed=LISTED) is False


def test_listing_the_servers_own_gateway_or_own_address_as_a_proxy_proves_nothing() -> None:
    """Where the address is hidden, EVERY visitor arrives as the gateway: a Host who lists it as a proxy would let any visitor write `X-Forwarded-For: 192.168.1.50` and be home.
    A listed proxy is believed only when it is neither the server's gateway nor its own address, i.e. a proxy of its own (a container on the server's network, another machine)."""
    gateway_listed = netaddr.networks(["172.19.0.1"])
    assert home("172.19.0.1", "192.168.1.50", listed=gateway_listed) is False
    assert home("172.19.0.1", "8.8.8.8, 192.168.1.50", listed=gateway_listed) is False
    own_listed = netaddr.networks(["172.19.0.3"])
    assert home("172.19.0.3", "192.168.1.50", listed=own_listed) is False
    whole_bridge = netaddr.networks(["172.19.0.0/16"])  # the whole network listed: the gateway is inside it
    assert home("172.19.0.1", "192.168.1.50", listed=whole_bridge) is False
    assert home("172.19.0.9", "192.168.1.50", listed=whole_bridge) is True, (
        "a proxy of its own inside the listed network is believed"
    )


def test_the_address_measured_on_the_owners_docker_desktop_is_the_gateway_and_is_not_home() -> None:
    """Audit B-56, measured on this project's own PC (Docker Desktop): a wrong login made through the PC's own address was counted by the server "against address 172.19.0.1",
    the Docker gateway of the compose network. That is the value the rule must exclude; the same value is the default gateway in the route table a container there reads."""
    measured = "172.19.0.1"
    own = netaddr.OwnNetwork(
        gateways=netaddr.default_gateways(DOCKER_BRIDGE) or frozenset(), addresses=frozenset({ipaddress.ip_address("172.19.0.3")})
    )
    assert ipaddress.ip_address(measured) in own.gateways
    assert home(measured, own=own) is False
    assert home(measured, "192.168.1.50", own=own) is False, "the forged header the same visitor could add"


def test_tailscales_range_is_not_proved_home() -> None:
    """Decided: a Tailscale address is a device on the Host's tailnet, which may be shared with other people; the page stays shut to it (the Host can list a proxy)."""
    assert home("100.64.1.5") is False
    assert home("100.100.100.100") is False


@pytest.mark.parametrize(
    "peer", ["8.8.8.8", "203.0.113.7", "169.254.10.10", "fd00::5", "fe80::1", "2001:db8::1", "::ffff:192.168.1.5"]
)
def test_everything_else_is_not_proved_home(peer: str) -> None:
    assert home(peer) is False


@pytest.mark.parametrize("peer", [None, "", "testclient", "garbage", "192.168.1"])
def test_a_peer_that_is_not_an_address_is_no(peer: str | None) -> None:
    assert home(peer) is False


def test_when_the_server_cannot_read_its_own_network_a_direct_visitor_is_no() -> None:
    """Fail shut: without knowing its own gateway and address the server cannot tell a visitor from the hidden-address gateway."""
    assert home("192.168.1.50", own=None) is False
    assert home("172.19.0.1", own=None) is False


def test_a_listed_proxy_is_not_believed_either_when_the_server_cannot_read_its_own_network() -> None:
    """Without its own gateway the server cannot rule out that the listed address IS the gateway that hides the visitors: fail shut, for the listed path too."""
    assert home("172.19.0.9", "192.168.1.50", own=None, listed=LISTED) is False


# --------------------------------------------------------------------------------------------------------------------- reading the server's own network

#: `/proc/net/route` of a container on a Docker bridge: the default route through 172.19.0.1 (little-endian hex `010013AC`), and the bridge's own network.
DOCKER_BRIDGE = (
    "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
    "eth0\t00000000\t010013AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
    "eth0\t000013AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n"
)


def test_the_default_gateway_is_read_from_the_route_table() -> None:
    assert netaddr.default_gateways(DOCKER_BRIDGE) == frozenset({ipaddress.ip_address("172.19.0.1")})


def test_a_route_table_with_two_default_routes_gives_both_gateways() -> None:
    two = DOCKER_BRIDGE + "eth1\t00000000\t0100A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
    assert netaddr.default_gateways(two) == frozenset({ipaddress.ip_address("172.19.0.1"), ipaddress.ip_address("192.168.0.1")})


def test_a_route_table_without_a_default_route_has_no_gateway_and_is_still_read() -> None:
    internal = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\neth0\t000013AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n"
    assert netaddr.default_gateways(internal) == frozenset()


@pytest.mark.parametrize("text", ["", "nonsense", "Iface\tDestination\n", None])
def test_a_route_table_that_cannot_be_read_is_not_an_empty_one(text: str | None) -> None:
    assert netaddr.default_gateways(text) is None


def test_the_reader_of_the_servers_own_network_says_none_when_there_is_no_route_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert netaddr.read_own_network(route_file=tmp_path / "missing", own_addresses=lambda: {"172.19.0.3"}) is None


def test_the_reader_puts_the_gateway_and_the_own_addresses_together(tmp_path) -> None:  # type: ignore[no-untyped-def]
    route = tmp_path / "route"
    route.write_text(DOCKER_BRIDGE, encoding="utf-8")

    own = netaddr.read_own_network(route_file=route, own_addresses=lambda: {"172.19.0.3", "not-an-address"})

    assert own is not None
    assert own.gateways == frozenset({ipaddress.ip_address("172.19.0.1")})
    assert ipaddress.ip_address("172.19.0.3") in own.addresses and ipaddress.ip_address("127.0.0.1") in own.addresses
    assert home("192.168.1.50", own=own) is True and home("172.19.0.1", own=own) is False and home("172.19.0.3", own=own) is False
