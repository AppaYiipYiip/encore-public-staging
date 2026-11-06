"""How does one Encore server behave with 20 (or more) people on it? A real server (uvicorn, a real socket, threads) and N simulated phones.

    cd server/encore_server && PYTHONPATH=. python tests/bench/bench_users.py [users] [seconds]

Each simulated phone does what a real one does, over and over: opens the app (the library feed, the playlists, the playback state, a picture pass),
asks for the signed address of thirty pictures and a song, and reports its playback position the way a playing phone does (a write). The answer is
the time every call took, by kind, so a read that is held up by a writer shows. Not a test (the name does not start with `test_`): a tool, kept so
the answer to "how many people can one server take" is something anybody can measure again (docs/tasks/AUDIT-BUILT-2026-11-05.md, B-10, B-18).
"""

from __future__ import annotations

import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from encore_server.api import create_app
from encore_server.config import Settings
from tests.conftest import FakeVerifier

V1 = "/encore/api/v1"


class Crowd(FakeVerifier):
    def __init__(self, n: int) -> None:
        super().__init__()
        for i in range(n):
            self.passwords[f"user{i:02d}"] = f"pw-user{i:02d}"


def main(users: int, seconds: float) -> None:
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(
        data_dir=tmp / "data", music_dir=tmp / "m", navidrome_url="http://navidrome.invalid", youtube=False, workers=False
    )
    app = create_app(settings, verifier=Crowd(users))
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    samples: dict[str, list[float]] = {}
    lock = threading.Lock()
    stop = time.monotonic() + seconds

    def timed(client: httpx.Client, kind: str, method: str, path: str, **kw) -> httpx.Response:
        t = time.perf_counter()
        r = client.request(method, path, **kw)
        ms = (time.perf_counter() - t) * 1000
        with lock:
            samples.setdefault(kind, []).append(ms)
        return r

    ready = threading.Barrier(users + 1)

    def phone(i: int) -> None:
        with httpx.Client(base_url=base, timeout=30) as c:
            login = c.post(
                f"{V1}/auth/login", json={"username": f"user{i:02d}", "password": f"pw-user{i:02d}", "deviceName": "bench"}
            ).json()
            c.headers["Authorization"] = f"Bearer {login['deviceToken']}"
            ref = c.post(
                f"{V1}/refs/resolve", json={"songs": [{"title": f"Song {i}", "artists": ["Artist"], "durationMs": 200000}]}
            ).json()["items"][0]["id"]
            ready.wait()
            while time.monotonic() < stop:
                timed(c, "read: library feed", "GET", f"{V1}/library/changes", params={"since": "0"})
                timed(c, "read: playlists", "GET", f"{V1}/playlists")
                timed(c, "read: playback state", "GET", f"{V1}/playback")
                timed(c, "read: picture pass", "GET", f"{V1}/covers/pass")
                for n in range(30):
                    timed(c, "read: a picture's signed address", "GET", f"{V1}/covers/cover-{n}/url", params={"size": 300})
                timed(c, "read: a song's signed address", "GET", f"{V1}/refs/{ref}/stream-url")
                timed(
                    c,
                    "write: playback position",
                    "PUT",
                    f"{V1}/playback",
                    json={"ref": ref, "positionMs": 1000, "playing": True, "rev": 0},
                )
                time.sleep(0.2)

    threads = [threading.Thread(target=phone, args=(i,)) for i in range(users)]
    for t in threads:
        t.start()
    ready.wait()
    began = time.monotonic()
    for t in threads:
        t.join()
    took = time.monotonic() - began
    server.should_exit = True

    total = sum(len(v) for v in samples.values())
    print(f"{users} phones for {took:.0f} s: {total} calls, {total / took:.0f} calls a second")
    print(f"{'kind':<40}{'calls':>7}{'median':>9}{'p95':>9}{'p99':>9}{'max':>9}   (ms)")
    for kind in sorted(samples):
        v = sorted(samples[kind])
        p95, p99 = (v[min(len(v) - 1, int(len(v) * q))] for q in (0.95, 0.99))
        print(f"{kind:<40}{len(v):>7}{statistics.median(v):>9.1f}{p95:>9.1f}{p99:>9.1f}{v[-1]:>9.1f}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20, float(sys.argv[2]) if len(sys.argv) > 2 else 15)
