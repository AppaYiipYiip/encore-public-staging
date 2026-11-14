"""The YouTube source as the rest of the server uses it: a song ref in, the bytes of its audio out (docs/04 section 4).

Resolving a ref to an upload is one search on YouTube Music (skipped when the ref already knows its video id, which an import or an earlier
play left on it), then one extraction of the stream's address (kept for most of an hour), then the bytes passed on with Range support.

**The memory of refusals (N-13).** Every public call below runs under [YoutubeSource._attempt]: a song the source has answered "no" about is refused at
once, inside the window, with no look-up at YouTube (`missing.py`); a "no" that is answered now is remembered. Only an ANSWER is a "no": a search that
could not be made, YouTube resting or refusing, a timeout, a file too big are never remembered. A stored upload that turns out to be gone does not make
the song missing by itself: one search for another upload comes first, and only when that also finds nothing is the song `removed` (or
`age_restricted`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, TypeVar

from ...missing import CODE_OF, REASON_OF, Standing
from .errors import DownloadError
from .lean import InProcessExtractor, LeanResolver, YtmusicApiSearcher
from .pace import Pacer
from .rest import CountedSearcher, Guarded, Lookups, Rest
from .scoring import Want
from .stream import StreamError, StreamProxy, Upstream

log = logging.getLogger("encore_server.sources.youtube")

T = TypeVar("T")

#: The codes that are an answer about the SONG (the stream's `_GONE`): the search found nothing, the upload is gone, it needs an age check.
_ANSWERS = frozenset(CODE_OF.values())


class Verdicts(Protocol):
    """The memory of refusals, as the source asks it (`verdicts.RefVerdicts` is the database's; a test gives a fake)."""

    def standing(self, ref_id: str) -> Standing | None: ...

    def record(self, ref_id: str, reason: str) -> None: ...

    def clear(self, ref_id: str) -> None: ...


class _Remembered(Exception):
    """A live memory says no: the code of the stream's error that says it. Each public call turns it into its own kind of refusal."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Wanted:
    """What the stream proxy needs to find the upload of a ref."""

    ref_id: str
    artist: str
    title: str
    album: str | None
    duration_s: int | None
    video_id: str | None
    #: The upload the ref remembered that turned out to be gone, while a search for another is made (N-13): the one a found upload replaces.
    replaces: str | None = None


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
        pace: Pacer | None = None,
        verdicts: Verdicts | None = None,
    ) -> None:
        self._pace = pace
        self._remember = remember_video
        self.verdicts = verdicts
        # A fault injected for a test of the whole app against a misbehaving YouTube (`ENCORE_FAULT`): what it makes up is not an answer about any song, so
        # nothing is remembered and nothing remembered is believed while one is set (a "no_results" would otherwise hold for a week on a test server).
        self._fault = fault.strip()
        self.rest = rest if rest is not None else Rest()
        # One count of look-ups at YouTube: the searches and the extractions (B8).
        lookups = Lookups()
        self._resolver = resolver or LeanResolver(CountedSearcher(YtmusicApiSearcher(), lookups), max_duration_s=6 * 3600)
        self._extractor = Guarded(
            extractor or InProcessExtractor(cache_dir=work_dir / "ytdlp-cache", fast_clients=fast_clients), self.rest, lookups
        )
        work_dir.mkdir(parents=True, exist_ok=True)
        self._proxy = proxy or StreamProxy(
            candidates=self._candidates, extract=self._extractor.extract, work_dir=work_dir, fault=fault, lookups=lookups
        )

    def _candidates(self, wanted: Wanted) -> list[tuple[str, str, int | None]]:
        if wanted.video_id:
            return [(wanted.video_id, wanted.title, wanted.duration_s)]
        # The search comes before the extraction, so the rest is obeyed here too: a tap that may not probe makes no search at all (B8).
        if not self.rest.probe_open():
            raise DownloadError("blocked", "YouTube is being given a rest")
        ranked = self._resolver.resolve_ranked(Want(wanted.artist, wanted.title, wanted.album, wanted.duration_s))
        found = [(s.candidate.video_id, s.candidate.title, s.candidate.duration_s) for s in ranked[:3]]
        if found and self._remember is not None:
            # Next time this song needs no search at all.
            try:
                self._remember(wanted.ref_id, found[0][0], wanted.replaces)
            except Exception:  # noqa: BLE001 - remembering is a nicety
                log.exception("could not remember the video of %s", wanted.ref_id)
        return found

    # ------------------------------------------------------------------ the memory of refusals

    def is_missing(self, wanted: Wanted) -> bool:
        """Whether the memory says no to this song now (inside its window): background work asks nothing about it."""
        if self.verdicts is None or self._fault:
            return False
        standing = self.verdicts.standing(wanted.ref_id)
        return standing is not None and standing.live

    def _attempt(self, wanted: Wanted, call: Callable[[Wanted], T]) -> T:
        """Runs one look-up under the memory: refused at once while a live memory says no, remembered when it is answered no now, and an old memory that
        did not hold (the window is over and the song was found) is cleared. Raises [_Remembered] for the first; what [call] raises, for the rest."""
        verdicts = self.verdicts
        if verdicts is None or self._fault:
            return call(wanted)
        before = verdicts.standing(wanted.ref_id)
        if before is not None and before.live:
            raise _Remembered(before.code)
        try:
            result = self._with_fallback(wanted, call)
        except (StreamError, DownloadError) as error:
            reason = REASON_OF.get(error.code)
            if reason is not None:
                verdicts.record(wanted.ref_id, reason)
            raise
        if before is not None:
            verdicts.clear(wanted.ref_id)
        return result

    @staticmethod
    def _with_fallback(wanted: Wanted, call: Callable[[Wanted], T]) -> T:
        try:
            return call(wanted)
        except (StreamError, DownloadError) as error:
            if not wanted.video_id or error.code not in _ANSWERS:
                raise
            # The upload the ref remembers is gone (or needs an age check): that does not make the SONG missing, another upload may exist. One search
            # for it first. The dead id stays in the ref until a live one replaces it (`replaces`): an empty column would be filled with the same dead id by
            # the next description of the song, which would void the memory.
            try:
                return call(replace(wanted, video_id=None, replaces=wanted.video_id))
            except (StreamError, DownloadError) as again:
                if again.code == "not_found":
                    raise error from None  # nothing else exists: the first answer (removed, an age check) stands
                raise

    # ------------------------------------------------------------------ the calls

    def open(self, wanted: Wanted, range_header: str | None) -> Upstream:
        try:
            return self._attempt(wanted, lambda w: self._proxy.open(w, range_header))
        except _Remembered as remembered:
            raise StreamError(remembered.code) from None

    def is_ready(self, wanted: Wanted) -> bool:
        """Whether a tap on this song needs no look-up at YouTube (its upload is known and its stream's address is kept)."""
        return bool(wanted.video_id) and self._proxy.has_address(str(wanted.video_id))

    def prepare(self, wanted: Wanted) -> bool:
        """Makes the song ready for a tap that has not come yet (its upload and its stream's address; no bytes): the next songs of somebody's queue.
        Background work: it waits its turn like every other request that nobody is waiting for, and it asks nothing while YouTube is being given a rest.
        Nothing is asked when the address is already kept, or when the memory says the song cannot be had."""

        def call(w: Wanted) -> bool:
            if self.is_ready(w):
                return True
            if self.rest.remaining() > 0:
                raise DownloadError("blocked", "YouTube is being given a rest")
            if self._pace is not None:
                self._pace.wait_turn()
            if not self._proxy.prepare(w):
                raise DownloadError("not_found")
            return True

        try:
            return self._attempt(wanted, call)
        except _Remembered:
            return False
        except DownloadError as error:
            if error.code == "not_found":
                return False  # the search answered with nothing (and `_attempt` remembered it)
            raise

    @property
    def lookups(self) -> Lookups:
        """The count of today's look-ups at YouTube (the updater's check is one of them)."""
        return self._extractor.lookups

    @property
    def pacer(self) -> Pacer | None:
        return self._pace

    def resting_for(self) -> float:
        """Seconds YouTube is being left alone for (0 when it is asked as usual): background work waits instead of asking."""
        return self.rest.remaining()

    def status(self) -> dict[str, Any]:
        return self.rest.snapshot()

    def find(self, wanted: Wanted) -> str | None:
        """The upload of the song (searching YouTube Music if the ref does not know it yet, and remembering what is found), or `None`.
        Nothing is extracted or downloaded: this is what imports use to say "found" or "not found". Background work: it waits its turn."""

        def call(w: Wanted) -> str:
            if self._pace is not None and not w.video_id:
                self._pace.wait_turn()
            found = self._candidates(w)
            if not found:
                raise DownloadError("not_found")
            return found[0][0]

        try:
            return self._attempt(wanted, call)
        except _Remembered:
            return None
        except DownloadError as error:
            if error.code == "not_found":
                return None
            raise

    def download(self, wanted: Wanted, stem: Path, *, max_bytes: int) -> Path:
        """The whole audio of the song, for keeping: `<stem>.<ext>`. Background work: it waits its turn."""

        def call(w: Wanted) -> Path:
            if self._pace is not None:
                self._pace.wait_turn()
            return self._proxy.download(w, stem, max_bytes=max_bytes)

        try:
            return self._attempt(wanted, call)
        except _Remembered as remembered:
            raise DownloadError(remembered.code) from None


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


__all__ = ["Verdicts", "Wanted", "YoutubeSource", "json", "wanted_from_ref"]
