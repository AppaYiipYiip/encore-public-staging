"""Stand-ins for YouTube and the music server so the whole service (and the
app against it) can run on a developer machine with no network and no
library. Selected with `FAKE_MODE=1`."""
from __future__ import annotations

import os
import time
from pathlib import Path

from .download import Downloaded
from .navidrome import Auth, Navidrome
from .resolve import Candidate, Scored, Want


class FakeResolver:
    """One hit that is exactly what was asked for (after a short wait, like a
    real search)."""

    def __init__(self, delay: float = 1.0) -> None:
        self._delay = delay

    def resolve(self, want: Want) -> Scored | None:
        time.sleep(self._delay)
        c = Candidate("fakeVideo01", want.title, "Fake - Topic",
                      want.duration_s, True, track=want.title,
                      artists=(want.artist,), album=want.album)
        return Scored(c, 10.0, ("fake",))


class FakeDownloader:
    def __init__(self, delay: float = 2.0) -> None:
        self._delay = delay

    def extract(self, video_id: str, info: Path) -> None:
        time.sleep(self._delay / 2)
        info.parent.mkdir(parents=True, exist_ok=True)
        info.write_text("{}", encoding="utf-8")

    def download(self, video_id: str, stem: Path,
                 duration_s: int | None = None,
                 info: Path | None = None) -> Downloaded:
        time.sleep(self._delay)
        stem.parent.mkdir(parents=True, exist_ok=True)
        path = stem.with_suffix(".opus")
        path.write_bytes(b"OggS" + os.urandom(2048))
        return Downloaded(path, "opus", 160)


class FakeNavidrome(Navidrome):
    """Accepts any credentials and "indexes" instantly under a fixed song id
    (an id that exists on the server the app is really connected to)."""

    def __init__(self, song_id: str | None = None) -> None:
        super().__init__("http://fake.invalid")
        self._song_id = song_id or os.environ.get("FAKE_SONG_ID")
        self._seen: set[str] = set()

    def verify(self, auth: Auth) -> bool:
        return True

    def start_scan(self, auth: Auth) -> bool:
        return True

    def find_song(self, auth: Auth, *, artist: str, title: str,
                  album: str | None = None,
                  relative_path: str | None = None) -> str | None:
        # The first look says "not there yet" (so the whole pipeline runs);
        # once a file was "placed" the song is there.
        key = f"{artist}|{title}".lower()
        if relative_path is None and key not in self._seen:
            self._seen.add(key)
            return None
        return self._song_id
