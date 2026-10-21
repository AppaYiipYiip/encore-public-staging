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

from .resolve import Runner, run_command


@dataclass(frozen=True)
class Tags:
    title: str
    artist: str
    album: str | None = None
    album_artist: str | None = None
    track: int | None = None
    disc: int | None = None
    year: int | None = None


def _flac_picture(data: bytes, mime: str = "image/jpeg") -> bytes:
    """A FLAC `PICTURE` block (front cover) for `METADATA_BLOCK_PICTURE`."""
    mime_b = mime.encode()
    return (
        struct.pack(">II", 3, len(mime_b)) + mime_b
        + struct.pack(">I", 0)              # description length
        + struct.pack(">IIII", 0, 0, 24, 0)  # width, height, depth, colours
        + struct.pack(">I", len(data)) + data
    )


def _with_mutagen(path: Path, tags: Tags, cover: bytes | None) -> bool:
    try:
        import mutagen  # type: ignore[import-not-found]
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
            if tags.album:
                audio["album"] = [tags.album]
            if tags.track:
                audio["tracknumber"] = [str(tags.track)]
            if tags.disc:
                audio["discnumber"] = [str(tags.disc)]
            if tags.year:
                audio["date"] = [str(tags.year)]
            if cover:
                audio["metadata_block_picture"] = [
                    base64.b64encode(_flac_picture(cover)).decode("ascii")
                ]
        elif suffix in (".m4a", ".mp4"):
            audio["\xa9nam"] = [tags.title]
            audio["\xa9ART"] = [tags.artist]
            audio["aART"] = [tags.album_artist or tags.artist]
            if tags.album:
                audio["\xa9alb"] = [tags.album]
            if tags.track:
                audio["trkn"] = [(tags.track, 0)]
            if tags.disc:
                audio["disk"] = [(tags.disc, 0)]
            if tags.year:
                audio["\xa9day"] = [str(tags.year)]
            if cover:
                from mutagen.mp4 import MP4Cover  # type: ignore[import-not-found]

                audio["covr"] = [MP4Cover(cover, MP4Cover.FORMAT_JPEG)]
        else:
            return False
        audio.save()
        return True
    except Exception:  # noqa: BLE001 - tagging must never lose a download
        return False


def ffmpeg_args(src: Path, dst: Path, tags: Tags) -> list[str]:
    """`ffmpeg` arguments that copy the audio and replace the global tags."""
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
    argv = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
            "-map", "0:a", "-map_metadata", "-1", "-c", "copy"]
    for key, value in meta:
        argv += ["-metadata", f"{key}={value}"]
    argv.append(str(dst))
    return argv


def _with_ffmpeg(path: Path, tags: Tags, runner: Runner,
                 ffmpeg: str) -> bool:
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
