"""Give the songs fetched before the catalogue lookup existed their album, cover, number and year.

    python -m encore_fetch.backfill PERSON            # look, change nothing, say what would change
    python -m encore_fetch.backfill PERSON --apply    # change the tags in place

Until 2026-10-18 a song that came from a playlist (no album, no cover in the request) was tagged as a "single named after
itself" with no picture: the library filled with one-song albums shown as a letter on a coloured tile. The fetch service
now looks the album up when it fetches (`catalogue.py`); this does the same for the songs already there.

What it touches: only audio files in the person's own folder whose album is missing or equal to the title and that have
no picture; only their album, track number, disc, year and cover tags, in place (mutagen). It never moves, renames,
re-encodes or deletes a file, so playlists, likes and play counts keep working; a file mutagen cannot write is left alone
(no fallback that would drop its other tags). The music server notices a changed file by itself.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .catalogue import Deezer, Meta
from .download import fetch_cover
from .library import PersonLayout
from .tagging import Tags, _with_mutagen

log = logging.getLogger("encore_fetch.backfill")

AUDIO = (".opus", ".ogg", ".m4a")


@dataclass(frozen=True)
class Found:
    """What a file says about itself."""

    title: str
    artist: str
    album: str | None
    has_cover: bool
    duration_s: int | None


def needs_a_look(found: Found) -> bool:
    """A single made up by the fetcher: no album of its own and no picture."""
    own = (found.album or "").strip().lower() in ("", found.title.strip().lower())
    return own and not found.has_cover and bool(found.title) and bool(found.artist)


def read_found(path: Path) -> Found | None:
    """The tags of [path], or `None` when it is not something this can read."""
    try:
        import mutagen  # type: ignore[import-not-found]

        audio = mutagen.File(str(path), easy=False)
    except Exception:  # noqa: BLE001
        return None
    if audio is None:
        return None
    seconds = int(audio.info.length) if getattr(audio, "info", None) and getattr(audio.info, "length", 0) else None
    if path.suffix.lower() in (".m4a", ".mp4"):
        def first(key):
            value = audio.get(key)
            return str(value[0]) if value else None

        return Found(first("\xa9nam") or "", first("\xa9ART") or "", first("\xa9alb"),
                     bool(audio.get("covr")), seconds)

    def tag(key):
        value = audio.get(key)
        return str(value[0]) if value else None

    return Found(tag("title") or "", tag("artist") or "", tag("album"),
                 bool(audio.get("metadata_block_picture")), seconds)


@dataclass
class Report:
    seen: int = 0
    wanted: int = 0
    found: int = 0
    changed: int = 0
    failed: int = 0

    def line(self, apply: bool) -> str:
        verb = "changed" if apply else "would change"
        return (f"{self.seen} files looked at, {self.wanted} have no album or picture of their own, "
                f"{self.found} are in the catalogue, {self.changed} {verb}, {self.failed} could not be written")


def run(
    files: Iterable[Path],
    *,
    read: Callable[[Path], Found | None],
    lookup: Callable[[str, str, int | None], Meta | None],
    cover: Callable[[str | None], bytes | None],
    write: Callable[[Path, Tags, bytes | None], bool],
    apply: bool,
    pause: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
    say: Callable[[str], None] = print,
    limit: int | None = None,
) -> Report:
    report = Report()
    for path in files:
        if limit is not None and report.changed >= limit:
            break
        report.seen += 1
        found = read(path)
        if found is None or not needs_a_look(found):
            continue
        report.wanted += 1
        meta = lookup(found.artist, found.title, found.duration_s)
        if pause:
            sleep(pause)
        if meta is None or not meta.album:
            continue
        report.found += 1
        say(f"{'+' if apply else '~'} {found.artist} - {found.title}  ->  {meta.album}"
            f"{f' ({meta.year})' if meta.year else ''}")
        if not apply:
            report.changed += 1
            continue
        tags = Tags(title=found.title, artist=found.artist, album=meta.album, track=meta.track, disc=meta.disc,
                    year=meta.year)
        if write(path, tags, cover(meta.cover_url)):
            report.changed += 1
        else:
            report.failed += 1
    return report


def audio_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO)


def main(argv: list[str] | None = None) -> int:
    from .config import Config

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("person", help="the person's name on the music server")
    parser.add_argument("--apply", action="store_true", help="write the tags (the default only looks)")
    parser.add_argument("--limit", type=int, default=None, help="stop after this many songs were changed")
    args = parser.parse_args(argv)

    config = Config.from_env()
    root = PersonLayout(config.music_dir, config.person_folders).root_for(args.person)
    if root is None or not root.is_dir():
        print(f"{args.person} has no folder of their own here; nothing to do", file=sys.stderr)
        return 1
    deezer = Deezer(config.work_dir / "catalogue-cache.json")
    report = run(
        audio_files(root), read=read_found, lookup=deezer.lookup, cover=fetch_cover,
        write=lambda path, tags, picture: _with_mutagen(path, tags, picture),
        apply=args.apply, pause=0.3, limit=args.limit)
    print(report.line(args.apply))
    if not args.apply and report.changed:
        print("nothing was changed; run again with --apply to write these tags")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
