"""Writing the tags the library needs (title, artist, album, number, year,
cover) into the downloaded file.

Two ways, best first:

1. `mutagen` (pure Python): all tags *and* the cover, in place.
2. `ffmpeg -c copy -metadata ...`: all tags, no cover. ffmpeg is already
   needed to remux the download, so tags are never skipped just because an
   optional Python package is missing.

A failure is reported, never raised: tagging must not lose a download.
"""

from __future__ import annotations

import base64
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..textnorm import is_placeholder_album
from .process import Runner, run_command


@dataclass(frozen=True)
class Tags:
    title: str
    artist: str
    album: str | None = None
    album_artist: str | None = None
    #: Each artist of the song on its own, in order. Written as the `ARTISTS` tag when there is more than one. Without it the music server reads the
    #: joined `artist` string ("Post Malone, Swae Lee") as ONE artist of that whole name, which has no album and is not in the artist index it gives
    #: to the apps: the song points at an artist nobody can open (audit B-118/B-119). With it the song is linked to every one of its artists (the
    #: first becomes the song's artist) and the joined string stays what is shown.
    artists: tuple[str, ...] = ()
    track: int | None = None
    disc: int | None = None
    year: int | None = None
    #: What lets a later scan (or another program) tell this is the same recording: written when known.
    isrc: str | None = None
    mbid: str | None = None


def tags_of(ref: dict[str, Any]) -> Tags:
    """The tags of a song's file, from the song's ref (the API's shape). THE one builder: the keeper tags a new file with it (N-34 slice 3) and the repair of the files already
    kept (slice 5, N-26's artist rewrite) retags with it, so a file agrees with its ref by one definition. **The music server's placeholder (`[Unknown Album]`) is no album** and
    is never written into a file (`textnorm.is_placeholder_album`): a tag of that name makes the music server list the song in the very bucket N-34 empties."""
    album = ref.get("album")
    return Tags(
        title=ref["title"],
        artist=", ".join(ref["artists"]),
        artists=tuple(ref["artists"]),
        album=None if is_placeholder_album(album) else album,
        album_artist=ref.get("albumArtist") or ref["artists"][0],
        track=ref.get("trackNo"),
        disc=ref.get("discNo"),
        year=ref.get("year"),
        isrc=ref.get("isrc"),
        mbid=ref.get("mbid"),
    )


def _flac_picture(data: bytes, mime: str = "image/jpeg") -> bytes:
    """A FLAC `PICTURE` block (front cover) for `METADATA_BLOCK_PICTURE`."""
    mime_b = mime.encode()
    return (
        struct.pack(">II", 3, len(mime_b))
        + mime_b
        + struct.pack(">I", 0)  # description length
        + struct.pack(">IIII", 0, 0, 24, 0)  # width, height, depth, colours
        + struct.pack(">I", len(data))
        + data
    )


def _with_mutagen(path: Path, tags: Tags, cover: bytes | None) -> bool:
    try:
        import mutagen
    except ImportError:
        return False
    try:
        audio = mutagen.File(str(path), easy=False)
        if audio is None:
            return False
        suffix = path.suffix.lower()
        if suffix in (".opus", ".ogg"):
            audio["title"] = [tags.title]
            audio["artist"] = [tags.artist]
            audio["albumartist"] = [tags.album_artist or tags.artist]
            if len(tags.artists) > 1:
                audio["artists"] = list(tags.artists)
            if tags.album:
                audio["album"] = [tags.album]
            if tags.track:
                audio["tracknumber"] = [str(tags.track)]
            if tags.disc:
                audio["discnumber"] = [str(tags.disc)]
            if tags.year:
                audio["date"] = [str(tags.year)]
            if tags.isrc:
                audio["isrc"] = [tags.isrc]
            if tags.mbid:
                audio["musicbrainz_trackid"] = [tags.mbid]
            if cover:
                audio["metadata_block_picture"] = [base64.b64encode(_flac_picture(cover)).decode("ascii")]
        elif suffix in (".m4a", ".mp4"):
            audio["\xa9nam"] = [tags.title]
            audio["\xa9ART"] = [tags.artist]
            audio["aART"] = [tags.album_artist or tags.artist]
            if len(tags.artists) > 1:
                audio["----:com.apple.iTunes:ARTISTS"] = [name.encode() for name in tags.artists]
            if tags.album:
                audio["\xa9alb"] = [tags.album]
            if tags.track:
                audio["trkn"] = [(tags.track, 0)]
            if tags.disc:
                audio["disk"] = [(tags.disc, 0)]
            if tags.year:
                audio["\xa9day"] = [str(tags.year)]
            if tags.isrc:
                audio["----:com.apple.iTunes:ISRC"] = [tags.isrc.encode()]
            if tags.mbid:
                audio["----:com.apple.iTunes:MusicBrainz Track Id"] = [tags.mbid.encode()]
            if cover:
                from mutagen.mp4 import MP4Cover

                audio["covr"] = [MP4Cover(cover, MP4Cover.FORMAT_JPEG)]  # type: ignore[no-untyped-call]
        else:
            return False
        audio.save()
        return True
    except Exception:  # noqa: BLE001 - tagging must never lose a download
        return False


def ffmpeg_args(src: Path, dst: Path, tags: Tags) -> list[str]:
    """`ffmpeg` arguments that copy the audio and replace the global tags.

    `ffmpeg -metadata` cannot write one tag twice, so this fallback cannot write `ARTISTS` (see [Tags.artists]): a song tagged this way is read by the
    music server as before, as one artist of the joined name.
    """
    meta: list[tuple[str, str]] = [
        ("title", tags.title),
        ("artist", tags.artist),
        ("album_artist", tags.album_artist or tags.artist),
    ]
    if tags.album:
        meta.append(("album", tags.album))
    if tags.track:
        meta.append(("track", str(tags.track)))
    if tags.disc:
        meta.append(("disc", str(tags.disc)))
    if tags.year:
        meta.append(("date", str(tags.year)))
    if tags.isrc:
        meta.append(("isrc", tags.isrc))
    if tags.mbid:
        meta.append(("musicbrainz_trackid", tags.mbid))
    argv = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-map", "0:a", "-map_metadata", "-1", "-c", "copy"]
    for key, value in meta:
        argv += ["-metadata", f"{key}={value}"]
    argv.append(str(dst))
    return argv


def _with_ffmpeg(path: Path, tags: Tags, runner: Runner, ffmpeg: str) -> bool:
    tmp = path.with_name(path.stem + ".tagged" + path.suffix)
    argv = ffmpeg_args(path, tmp, tags)
    argv[0] = ffmpeg
    result = runner(argv, 60)
    if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        return False
    os.replace(tmp, path)
    return True


def write_tags(
    path: Path,
    tags: Tags,
    cover: bytes | None = None,
    *,
    runner: Runner = run_command,
    ffmpeg: str = "ffmpeg",
) -> bool:
    """Returns `True` when tags were written (by either way)."""
    if _with_mutagen(path, tags, cover):
        return True
    return _with_ffmpeg(path, tags, runner, ffmpeg)


def file_length_ms(path: Path) -> int | None:
    """The length of an audio file in milliseconds, or `None` (no such file, a format `mutagen` cannot read, `mutagen` not installed). Reads only: the album pass (N-34
    slice 2) and its dry run compare a kept FILE's own length with the catalogue's, because the import's listing is 1 to 12 s off (N-11)."""
    try:
        import mutagen

        audio = mutagen.File(str(path))
        length = float(audio.info.length) if audio is not None and audio.info is not None else 0.0
    except Exception:  # noqa: BLE001 - any unreadable file is "no length", never a crash of a pass
        return None
    return round(length * 1000) if length > 0 else None
