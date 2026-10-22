"""The live channel (docs/17 section 4): one websocket per running app; events make things faster, never correct.

Events (server to app) are `library.changed {cursor}`, `playback.changed {state}`, `device.takeover {by}`, later `import.progress`.
Writes happen in worker threads and the sockets live on the event loop, so [Hub.publish] is safe to call from any thread.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any


class Connection:
    def __init__(self, person: str, device: str | None) -> None:
        self.person = person
        self.device = device
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)


class Hub:
    def __init__(self) -> None:
        self._connections: dict[str, set[Connection]] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach(self, person: str, device: str | None) -> Connection:
        """Called from the websocket handler (on the loop)."""
        self._loop = asyncio.get_running_loop()
        connection = Connection(person, device)
        with self._lock:
            self._connections.setdefault(person, set()).add(connection)
        return connection

    def detach(self, connection: Connection) -> None:
        with self._lock:
            members = self._connections.get(connection.person)
            if members is not None:
                members.discard(connection)
                if not members:
                    del self._connections[connection.person]

    def count(self, person: str | None = None) -> int:
        with self._lock:
            if person is not None:
                return len(self._connections.get(person, ()))
            return sum(len(m) for m in self._connections.values())

    def publish(
        self, person: str, event: dict[str, Any], *, except_device: str | None = None, only_device: str | None = None
    ) -> None:
        """Tells a person's connected devices. [except_device] is the one that caused it (it knows); [only_device] sends to one."""
        loop = self._loop
        if loop is None:
            return
        with self._lock:
            targets = [
                c
                for c in self._connections.get(person, ())
                if (except_device is None or c.device != except_device) and (only_device is None or c.device == only_device)
            ]
        for connection in targets:
            loop.call_soon_threadsafe(self._offer, connection, event)

    @staticmethod
    def _offer(connection: Connection, event: dict[str, Any]) -> None:
        try:
            connection.queue.put_nowait(event)
        except asyncio.QueueFull:
            # A client that cannot keep up gets a hint to ask again instead of a backlog: events are never needed for correctness.
            try:
                connection.queue.get_nowait()
                connection.queue.put_nowait({"type": "resync"})
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
