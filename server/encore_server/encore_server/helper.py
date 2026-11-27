"""The Encore server's side of the helper (docs/36 section 3): one request line over a local socket, one answer, the seven actions and no others.

The helper runs as root on the computer and does a few fixed things; this module is the only way the server asks. It sends `TOKEN ACTION` and reads `result:`, `item:`, `done:` and `failed:` lines
until the helper closes the connection. **Nothing here can name anything but one of the seven actions** (a request for another one never leaves this process), no action takes an argument, and no
answer is trusted beyond its shape: a line that is not one of the four kinds is dropped, the answer is capped, and an answer that does not end in `done:` or `failed:` is an unavailable helper.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings

#: The whole list (docs/36 section 3). Restore and update are not here on purpose.
ACTIONS = frozenset({"status", "backup.make", "backup.list", "away.status", "away.on", "away.off", "restart"})
MAX_ANSWER_BYTES = 64 * 1024
NOT_INSTALLED = (
    "The admin pages cannot do this until the helper is installed: on the server computer run  sudo encore helper install"
)


class HelperUnavailable(Exception):
    """The helper cannot be reached or did not answer properly; the message is a sentence for the Host."""

    def __init__(self, message: str = NOT_INSTALLED) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class HelperAnswer:
    results: dict[str, str] = field(default_factory=dict)
    items: list[list[str]] = field(default_factory=list)
    done: str | None = None
    failed: str | None = None


class HelperClient:
    def __init__(
        self,
        path: str,
        token: str,
        *,
        timeout: float = 90.0,
        connect: Callable[[], socket.socket] | None = None,
    ) -> None:
        self._path = path
        self._token = token
        self._timeout = timeout
        self._connect = connect

    @staticmethod
    def from_settings(settings: Settings) -> HelperClient | None:
        return (
            HelperClient(settings.helper_socket, settings.helper_token)
            if settings.helper_socket and settings.helper_token
            else None
        )

    def available(self) -> bool:
        """Is there a helper to ask: the socket is there (a test client with its own connection is always)."""
        if self._connect is not None:
            return True
        try:
            Path(self._path).stat()
        except FileNotFoundError:
            return False
        except PermissionError:
            return True  # it is there and this process may not open it: `call` says so in words
        except OSError:
            return False
        return True

    def call(self, action: str) -> HelperAnswer:
        if action not in ACTIONS:
            raise ValueError(f"not an action of the helper: {action!r}")
        try:
            sock = self._connect() if self._connect is not None else self._open()
        except PermissionError as error:
            raise HelperUnavailable(
                "The server may not open the helper's socket (a permission). On the server computer run  sudo encore helper install  and then  sudo encore restart"
            ) from error
        except (
            OSError,
            AttributeError,
        ) as error:  # no such socket (a computer without the helper; a platform without unix sockets)
            raise HelperUnavailable() from error
        deadline = time.monotonic() + self._timeout
        data = b""
        try:
            sock.settimeout(self._timeout)
            sock.sendall(f"{self._token} {action}\n".encode("ascii"))
            while len(data) < MAX_ANSWER_BYTES:
                if time.monotonic() > deadline:
                    raise HelperUnavailable("The helper took too long to answer.")
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        except HelperUnavailable:
            raise
        except OSError as error:
            raise HelperUnavailable(
                "The helper did not answer. Is it running? sudo systemctl status encore-helper.socket"
            ) from error
        finally:
            sock.close()
        return _parse(data.decode("utf-8", "replace"))

    def _open(self) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # type: ignore[attr-defined,unused-ignore]
        try:
            sock.settimeout(5.0)
            sock.connect(self._path)
        except OSError:
            sock.close()
            raise
        return sock


def _parse(text: str) -> HelperAnswer:
    results: dict[str, str] = {}
    items: list[list[str]] = []
    done: str | None = None
    failed: str | None = None
    for line in text.splitlines():
        kind, sep, rest = line.partition(": ")
        if not sep:  # a line without its mark is not an answer line
            continue
        if kind == "result" and "=" in rest:
            key, _, value = rest.partition("=")
            results[key.strip()] = value.strip()
        elif kind == "item":
            items.append(rest.split(" "))
        elif kind == "done":
            done = rest
        elif kind == "failed":
            failed = rest
    if done is None and failed is None:
        raise HelperUnavailable("The helper did not finish its answer.")
    return HelperAnswer(results, items, done, failed)
