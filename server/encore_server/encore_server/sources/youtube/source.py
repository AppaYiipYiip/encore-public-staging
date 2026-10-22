"""The YouTube source as the rest of the server uses it: a song ref in, the bytes of its audio out (docs/04 section 4).

Resolving a ref to an upload is one search on YouTube Music (skipped when the ref already knows its video id, which an import or an earlier
play left on it), then one extraction of the stream's address (kept for most of an hour), then the bytes passed on with Range support.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .lean import InProcessExtractor, LeanResolver, YtmusicApiSearcher
from .rest import Guarded, Rest
from .scoring import Want
from .stream import StreamProxy, Upstream

log = logging.getLogger("encore_server.sources.youtube")


@dataclass(frozen=True)
class Wanted:
    """What the stream proxy needs to find the upload of a ref."""

    ref_id: str
    artist: str
    title: str
    album: str | None
    duration_s: int | None
    video_id: str | None


class YoutubeSource:
    def __init__(
        self,
        work_dir: Path,
        *,
        resolver: Any | None = None,
        extractor: Any | None = None,
        proxy: StreamProxy | None = None,
        fast_clients: tuple[str, ...] = ("visionos",),
        fault: str = "",
        remember_video: Any | None = None,
        rest: Rest | None = None,
    ) -> None:
        self._remember = remember_video
        self.rest = rest if rest is not None else Rest()
        self._resolver = resolver or LeanResolver(YtmusicApiSearcher(), max_duration_s=6 * 3600)
        self._extractor = Guarded(
            extractor or InProcessExtractor(cache_dir=work_dir / "ytdlp-cache", fast_clients=fast_clients), self.rest
        )
        work_dir.mkdir(parents=True, exist_ok=True)
        self._proxy = proxy or StreamProxy(
            candidates=self._candidates, extract=self._extractor.extract, work_dir=work_dir, fault=fault
        )

    def _candidates(self, wanted: Wanted) -> list[tuple[str, str, int | None]]:
        if wanted.video_id:
            return [(wanted.video_id, wanted.title, wanted.duration_s)]
        ranked = self._resolver.resolve_ranked(Want(wanted.artist, wanted.title, wanted.album, wanted.duration_s))
        found = [(s.candidate.video_id, s.candidate.title, s.candidate.duration_s) for s in ranked[:3]]
        if found and self._remember is not None:
            # Next time this song needs no search at all.
            try:
                self._remember(wanted.ref_id, found[0][0])
            except Exception:  # noqa: BLE001 - remembering is a nicety
                log.exception("could not remember the video of %s", wanted.ref_id)
        return found

    def open(self, wanted: Wanted, range_header: str | None) -> Upstream:
        return self._proxy.open(wanted, range_header)

    def resting_for(self) -> float:
        """Seconds YouTube is being left alone for (0 when it is asked as usual): background work waits instead of asking."""
        return self.rest.remaining()

    def status(self) -> dict[str, Any]:
        return self.rest.snapshot()

    def find(self, wanted: Wanted) -> str | None:
        """The upload of the song (searching YouTube Music if the ref does not know it yet, and remembering what is found), or `None`.
        Nothing is extracted or downloaded: this is what imports use to say "found" or "not found"."""
        found = self._candidates(wanted)
        return found[0][0] if found else None

    def download(self, wanted: Wanted, stem: Path, *, max_bytes: int) -> Path:
        """The whole audio of the song, for keeping: `<stem>.<ext>`."""
        return self._proxy.download(wanted, stem, max_bytes=max_bytes)


def wanted_from_ref(ref: dict[str, Any]) -> Wanted:
    """From the API's shape of a ref."""
    duration = ref.get("durationMs")
    return Wanted(
        ref_id=ref["id"],
        artist=(ref.get("artists") or [""])[0],
        title=ref["title"],
        album=ref.get("album"),
        duration_s=round(duration / 1000) if isinstance(duration, int) else None,
        video_id=ref.get("videoId"),
    )


__all__ = ["Wanted", "YoutubeSource", "json", "wanted_from_ref"]
