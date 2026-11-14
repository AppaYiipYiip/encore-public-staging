"""The guard under every server test (`conftest._no_outside_network`): a test never reaches the real catalogue, YouTube or anything else outside.

P2-12 slice 1 puts a second budget-and-politeness layer between the server and Deezer; the proof that it holds is worthless if a test can step around it, so
any connection to an address that is not this machine (or the music server an integration test names in `IT_NAVIDROME_URL`) is refused, written down, and
fails the test that made it when the test ends, because the code that asks swallows errors on purpose.
"""

from __future__ import annotations

import socket

import pytest

from tests.conftest import allowed_hosts


def test_a_connection_to_an_outside_address_is_refused_and_written_down(_no_outside_network: list[str]) -> None:
    with pytest.raises(OSError, match="outside"):
        socket.create_connection(("203.0.113.7", 443), timeout=1)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock, pytest.raises(OSError, match="outside"):
        sock.connect_ex(("198.51.100.9", 80))
    assert [entry.split(":")[0] for entry in _no_outside_network] == ["203.0.113.7", "198.51.100.9"]
    _no_outside_network.clear()  # these two were on purpose: the end of the test must not blame it


def test_this_machine_is_not_outside(_no_outside_network: list[str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        with socket.create_connection(listener.getsockname(), timeout=2):
            pass
    a, b = socket.socketpair()  # what an event loop on Windows builds its wake-up from
    a.close()
    b.close()
    assert _no_outside_network == []


def test_the_music_server_an_integration_test_names_is_not_outside() -> None:
    allowed = allowed_hosts("http://music.example.invalid:4533")
    assert "music.example.invalid" in allowed
    assert allowed_hosts("") == set(), "no integration test running: nothing but this machine"
