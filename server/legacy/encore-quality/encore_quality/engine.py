"""The journey of one request, step by step (docs/46 section 1):

    queued -> getting_ready -> searching <-> downloading -> delivering -> ready
                   \\-> no_match            \\-> not_found (tried again later, a few times)

`Engine.step()` looks at every request that is in somebody's hands and moves each one as far as it can go right now. It keeps no state of
its own: everything it knows is in the store and in Lidarr, so a restart, a crash or a slow week changes nothing. It is called every
twenty seconds or so; a step never waits for Lidarr, slskd or the music server to finish something, it looks again next time.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import delivery, store
from .delivery import DeliveryError
from .lidarr import Lidarr, LidarrError
from .matching import Song, choose
from .navidrome import Navidrome
from .slskd import Slskd
from .store import Store, Want
from .textnorm import norm_title, ratio
from .wiring import Wiring

log = logging.getLogger("encore_quality.engine")

LOSSLESS = {"flac", "alac", "wav", "ape", "wv", "aiff"}
DAY = 86400.0


@dataclass(frozen=True)
class Limits:
    #: How long an album is looked for before it is called "not found" (Soulseek can take days; a week is generous).
    give_up_days: float = 7.0
    #: How long to wait before looking again, and how many times in all.
    retry_days: float = 7.0
    max_attempts: int = 3
    #: Albums started per day: a polite pace on a shared network, and a bound on what a big import can ask for.
    daily_cap: int = 40
    #: Do not start new albums when less than this is free.
    min_free_gb: float = 5.0
    #: How far a song's length may differ from the same song on the album before it is called a different edition.
    duration_tolerance_s: float = 3.0


class Engine:
    def __init__(self, *, store: Store, lidarr: Lidarr, navidrome: Navidrome, music: Path, wiring: Callable[[], Wiring | None],
                 slskd: Slskd | None = None, limits: "Limits | Callable[[], Limits]" = Limits(), soulseek_on: Callable[[], bool] = lambda: True,
                 clock: Callable[[], float] = time.time, free_bytes: Callable[[Path], int] = delivery.free_bytes) -> None:
        self._store = store
        self._lidarr = lidarr
        self._nd = navidrome
        self._music = music
        self._wiring = wiring
        self._slskd = slskd
        self._limits_source = limits if callable(limits) else (lambda: limits)
        self._soulseek_on = soulseek_on
        self._clock = clock
        self._free = free_bytes
        self._last_scan = 0.0

    @property
    def _limits(self) -> Limits:
        return self._limits_source()  # read each time: the owner can change them while the server runs

    # ------------------------------------------------------------------ one pass

    def step(self) -> None:
        self._retry_due()
        for want in self._store.in_state(*store.ACTIVE):
            try:
                self._advance(want)
            except LidarrError as error:
                log.warning("request %s (%s): Lidarr: %s", want.id, want.title, error)
                self._say(want, detail="The quality tools are not answering. This is tried again by itself.")
            except Exception:  # noqa: BLE001 - one request must never stop the others
                log.exception("request %s (%s) could not be advanced", want.id, want.title)

    def _advance(self, want: Want) -> None:
        {store.QUEUED: self._match, store.GETTING_READY: self._get_ready, store.SEARCHING: self._search,
         store.DOWNLOADING: self._search, store.DELIVERING: self._deliver}[want.state](want)

    def _retry_due(self) -> None:
        now = self._clock()
        for want in self._store.in_state(store.NOT_FOUND):
            if want.next_try is not None and want.next_try <= now and want.attempts < self._limits.max_attempts:
                self._store.update(want.id, state=store.QUEUED, detail="Looking again.", next_try=None)

    def _say(self, want: Want, state: str | None = None, **changes: object) -> Want:
        if state is not None:
            changes["state"] = state
        return self._store.update(want.id, **changes) or want

    # ------------------------------------------------------------------ queued: which release is this?

    def _match(self, want: Want) -> None:
        wiring = self._wiring()
        if wiring is None or self._lidarr.version() is None:
            self._say(want, detail="The quality tools are starting up. This is tried again by itself.")
            return
        if not self._soulseek_on():
            self._say(want, detail="High quality is not switched on for this server yet. It starts when the owner switches it on.")
            return
        if self._started_today() >= self._limits.daily_cap:
            self._say(want, detail="Today's limit of albums was reached. It carries on tomorrow.")
            return
        if self._free(self._music) < self._limits.min_free_gb * 1024 ** 3:
            self._say(want, detail="The server is almost out of space, so it is not asking for more music.")
            return
        file = self._nd.file_of(want.song_id)
        if file is None:
            self._say(want, store.FAILED, detail="This song is not in the library any more.")
            return
        if file.suffix in LOSSLESS or (file.bit_rate or 0) >= 320:
            self._say(want, store.READY, detail=f"Already in the best quality ({file.suffix.upper()}).")
            return
        song = Song(want.artist, want.album, want.title, want.year, file.release_group or None)
        choice = choose(song, self._lidarr.album_lookup(f"{want.artist} {want.album or want.title}"))
        if not choice.found and want.album:
            choice = choose(song, self._lidarr.album_lookup(f"{want.artist} {want.title}"))
        if not choice.found:
            self._say(want, store.NO_MATCH, detail=choice.reason)
            return
        album = choice.album or {}
        known = {a.get("foreignArtistId"): a for a in self._lidarr.artists()}
        mb_artist = (album.get("artist") or {}).get("foreignArtistId")
        if mb_artist in known:
            artist_id = int(known[mb_artist]["id"])
        else:
            if self._another_artist_loading(want):
                self._say(want, detail="Waiting its turn: another artist's releases are still loading.")
                return
            artist_id = int(self._lidarr.add_artist(album["artist"], quality_id=wiring.quality_id, metadata_id=wiring.metadata_id,
                                                    root_path=wiring.pool)["id"])
        self._count_started()
        self._say(want, store.GETTING_READY, release_group=str(album.get("foreignAlbumId") or ""), lidarr_artist=artist_id,
                  detail=f"Getting ready: learning about {want.artist}'s releases. This can take a few minutes.")

    def _another_artist_loading(self, want: Want) -> bool:
        for other in self._store.in_state(store.GETTING_READY):
            if other.id != want.id and other.lidarr_artist and self._lidarr.refreshing(other.lidarr_artist):
                return True
        return False

    def _started_today(self) -> int:
        return int(self._store.setting(f"started:{self._day()}", "0") or 0)

    def _count_started(self) -> None:
        self._store.set_setting(f"started:{self._day()}", str(self._started_today() + 1))

    def _day(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self._clock()))

    # ------------------------------------------------------------------ getting ready: the album is known to Lidarr, so want it

    def _get_ready(self, want: Want) -> None:
        artist_id = want.lidarr_artist
        if artist_id is None:
            self._say(want, store.QUEUED)
            return
        if self._lidarr.refreshing(artist_id):
            self._say(want, detail=f"Getting ready: learning about {want.artist}'s releases. This can take a few minutes.")
            return
        album = next((a for a in self._lidarr.albums(artist_id) if a.get("foreignAlbumId") == want.release_group), None)
        if album is None or not album.get("releases"):
            self._say(want, store.NO_MATCH, detail="The music catalogue lists that album but has no details for it.")
            return
        track = self._track(want, self._lidarr.tracks(album["id"]))
        if track is None:
            self._say(want, store.NO_MATCH, detail="Found the album, but this song is not on it (a different edition).")
            return
        if track.get("hasFile"):
            self._to_delivery(want, "It is already here. Putting it in place.", lidarr_album=album["id"])
            return
        self._lidarr.ensure_artist_monitored(artist_id)  # an artist the owner added by hand may not be: its albums would never be wanted
        self._lidarr.monitor_albums([album["id"]], True)
        self._say(want, store.SEARCHING, lidarr_album=album["id"], next_try=self._clock() + self._limits.give_up_days * DAY,
                  detail="Looking for it. This can take minutes, days, or never.")

    def _track(self, want: Want, tracks: list[dict]) -> dict | None:
        """The album's track that is this song: by name, then by number and length when two share a name."""
        wanted = norm_title(want.title)
        same = [t for t in tracks if norm_title(str(t.get("title") or "")) == wanted]
        if not same:
            same = [t for t in tracks if ratio(norm_title(str(t.get("title") or "")), wanted) >= 0.9]
        if not same:
            return None

        def apart(track: dict) -> tuple:
            seconds = (track.get("duration") or 0) / 1000
            return (abs(seconds - want.duration) if want.duration and seconds else 0.0,
                    abs(int(track.get("trackNumber") or 0) - (want.track or 0)) if want.track else 0)

        return min(same, key=apart)

    # ------------------------------------------------------------------ searching and downloading: wait, and say how it is going

    def _search(self, want: Want) -> None:
        if want.lidarr_album is None:
            self._say(want, store.GETTING_READY)
            return
        album = self._lidarr.album(want.lidarr_album)
        track = self._track(want, self._lidarr.tracks(want.lidarr_album))
        if track is not None and track.get("hasFile"):
            self._to_delivery(want, "It arrived. Putting it in place.")
            return
        if not album.get("monitored"):
            self._lidarr.monitor_albums([want.lidarr_album], True)  # a refresh of the artist can undo it
        if want.next_try is not None and self._clock() > want.next_try:
            self._give_up(want)
            return
        downloading = bool(self._slskd and self._slskd.downloading(str(album.get("title") or want.album)))
        if downloading:
            self._say(want, store.DOWNLOADING, detail="Downloading it now.")
        else:
            self._say(want, store.SEARCHING, detail="Looking for it. This can take minutes, days, or never.")

    def _give_up(self, want: Want) -> None:
        attempts = want.attempts + 1
        album_id = want.lidarr_album
        if album_id is not None and not any(o.id != want.id and o.lidarr_album == album_id for o in self._store.in_state(*store.ACTIVE)):
            self._lidarr.monitor_albums([album_id], False)  # so Soularr stops asking the network for it
        if attempts < self._limits.max_attempts:
            self._say(want, store.NOT_FOUND, attempts=attempts, next_try=self._clock() + self._limits.retry_days * DAY,
                      detail="Nobody is sharing it right now. Encore will look again in a week.")
        else:
            self._say(want, store.NOT_FOUND, attempts=attempts, next_try=None, detail="Couldn't find it after three tries.")

    # ------------------------------------------------------------------ delivering: the better copy is in the pool

    def _to_delivery(self, want: Want, detail: str, **changes: object) -> None:
        """It is in the pool: say so, and put it in place in the same step (nobody should wait twenty seconds for nothing)."""
        self._deliver(self._say(want, store.DELIVERING, detail=detail, **changes))

    def _deliver(self, want: Want) -> None:
        wiring = self._wiring()
        if want.lidarr_album is None or wiring is None:
            self._say(want, store.GETTING_READY)
            return
        track = self._track(want, self._lidarr.tracks(want.lidarr_album))
        if track is None or not track.get("hasFile"):
            self._say(want, store.SEARCHING)  # the file was taken away again: back to waiting
            return
        seconds = (track.get("duration") or 0) / 1000
        if want.duration and seconds and abs(seconds - want.duration) > self._limits.duration_tolerance_s:
            self._say(want, store.NO_MATCH, detail="What was found is a different edition of the song (a different length), so it was not used.")
            return
        files = {f["id"]: f for f in self._lidarr.track_files(want.lidarr_album)}
        found = files.get(track.get("trackFileId"))
        if found is None:
            self._say(want, detail="Waiting for the file to be filed away.")
            return
        quality = str(((found.get("quality") or {}).get("quality") or {}).get("name") or "better")
        try:
            placed = delivery.place(self._music, want.quick_path, self._pool_file(wiring, str(found.get("path") or "")))
        except DeliveryError as error:
            log.warning("request %s (%s): %s", want.id, want.title, error)
            self._say(want, store.FAILED, detail=f"Could not put the better copy in place: {error}")
            return
        song = self._nd.find_by_path(placed.quality_rel)
        if song is None:
            self._scan_soon()
            self._say(want, detail="Putting it in place: waiting for the music server to notice it.")
            return
        self._store.add_upgrade(want.person, want.song_id, song.id, quality)
        self._say(want, store.READY, new_song_id=song.id, detail=f"Now in the best quality ({quality}).")
        log.info("request %s: %s - %s is now %s (%s)", want.id, want.artist, want.title, quality, song.id)

    def _pool_file(self, wiring: Wiring, lidarr_path: str) -> Path:
        """Lidarr's path of the file as this service sees it (the same mount, so usually the same path)."""
        pool = wiring.pool.rstrip("/")
        if lidarr_path.startswith(pool + "/"):
            return self._music / delivery.POOL_DIR / lidarr_path[len(pool) + 1:]
        return Path(lidarr_path)

    def _scan_soon(self) -> None:
        now = self._clock()
        if now - self._last_scan >= 30 and not self._nd.scanning():
            self._last_scan = now
            self._nd.start_scan()
