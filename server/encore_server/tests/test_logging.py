"""The server's log must not hold anything a login can be guessed from."""

from __future__ import annotations

import logging

from encore_server.__main__ import configure_logging


def test_the_requests_to_the_music_server_are_not_logged_with_their_login_tokens() -> None:
    configure_logging("INFO")

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
