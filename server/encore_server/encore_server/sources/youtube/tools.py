"""The yt-dlp the server runs: the image's own, or a newer one it fetched, checked and switched to by itself (docs/11 ADR-R39).

A newer yt-dlp is a plain wheel (pure Python, no dependencies) that Python can import straight from the file. It lives in `<data>/tools/yt-dlp/`:

    wheels/yt_dlp-2026.11.02-py3-none-any.whl     downloaded, its sha256 checked against what PyPI said
    current.json                                  {"version", "wheel", "sha256"}: the one the next start puts first on the import path

Nothing in a running process changes: the wheel is put first on `sys.path` (and in `PYTHONPATH`, so a child process and the playlist reader see
the same copy) once, at start, before anything imports yt_dlp. Whatever is wrong with the pointer (a missing or half-written wheel, a copied
folder, a hash that no longer matches) costs one log line and the image's own copy is used, and the pointer is removed, so that nothing waits for it and the
next daily check fetches the release anew; a start never fails because of this folder.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import os
import sys
import tempfile
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("encore_server.youtube.tools")

PACKAGE = "yt-dlp"
#: A release has to be this old before it is used: a broken or hostile one is usually pulled within a day.
MIN_RELEASE_AGE_S = 24 * 3600.0


def version_key(text: str) -> tuple[int, ...] | None:
    """`2026.10.21` -> (2026, 10, 21). `None` for anything that is not dotted numbers (a pre-release, a typo): such a version is never used."""
    parts = text.strip().split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Pointer:
    version: str
    wheel: str
    sha256: str


@dataclass(frozen=True)
class Active:
    """The runtime copy this process was started with."""

    version: str
    wheel: Path


@dataclass(frozen=True)
class Release:
    version: str
    filename: str
    url: str
    sha256: str
    uploaded_at: float


class ToolStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.wheels = root / "wheels"
        self.pointer_file = root / "current.json"
        self.state_file = root / "state.json"
        #: The version the server last restarted for. Its own file: the updater and the restarter write at different times and must not undo each other.
        self.restarted_file = root / "restarted-for"

    # ---------------------------------------------------------------- the pointer

    def read_pointer(self) -> Pointer | None:
        try:
            data = json.loads(self.pointer_file.read_text(encoding="utf-8"))
            pointer = Pointer(str(data["version"]), str(data["wheel"]), str(data["sha256"]))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as error:
            log.warning("yt-dlp: the pointer in %s cannot be read (%s); using the image's own copy", self.pointer_file, error)
            return None
        if "/" in pointer.wheel or "\\" in pointer.wheel or not pointer.wheel.endswith(".whl"):
            log.warning(
                "yt-dlp: the pointer names %r, which is not a wheel in the tools folder; using the image's own copy",
                pointer.wheel,
            )
            return None
        return pointer

    def clear_pointer(self) -> None:
        """Forgets the pointer, so a pointer that cannot be used is not waited for (and restarted for) again and again; the next check fetches the release anew."""
        try:
            self.pointer_file.unlink(missing_ok=True)
        except OSError as error:
            log.warning("yt-dlp: the unusable pointer could not be removed (%s)", error)
        self.prune(())  # its wheels are no use to anybody now (about 3 MB each)

    def verified_wheel(self, pointer: Pointer) -> Path | None:
        """The pointer's wheel, only when it is there, whole and what was stored (an interrupted write or a copied folder fail here)."""
        path = self.wheels / pointer.wheel
        try:
            actual = sha256_of(path)
        except OSError as error:
            log.warning("yt-dlp %s: its file is missing or unreadable (%s); using the image's own copy", pointer.version, error)
            return None
        if actual != pointer.sha256:
            log.warning("yt-dlp %s: its file does not match the stored checksum; using the image's own copy", pointer.version)
            return None
        return path

    def write_pointer(self, pointer: Pointer) -> None:
        self._write_json(self.pointer_file, {"version": pointer.version, "wheel": pointer.wheel, "sha256": pointer.sha256})

    # ---------------------------------------------------------------- the wheels

    def save_wheel(self, release: Release, data: bytes) -> Path:
        """Stores a downloaded wheel (temporary file, check, rename). Raises `ValueError` when the bytes are not what PyPI described."""
        actual = hashlib.sha256(data).hexdigest()
        if actual != release.sha256:
            raise ValueError(f"yt-dlp {release.version}: the download does not match PyPI's checksum")
        self.wheels.mkdir(parents=True, exist_ok=True)
        target = self.wheels / release.filename
        fd, temp = tempfile.mkstemp(dir=self.wheels, prefix=".part-", suffix=".whl")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temp, target)
        finally:
            Path(temp).unlink(missing_ok=True)
        return target

    def prune(self, keep: Collection[str]) -> None:
        """Deletes every stored wheel not in [keep] (file names), and leftovers of an interrupted download."""
        if not self.wheels.is_dir():
            return
        for path in self.wheels.iterdir():
            if path.name not in keep:
                path.unlink(missing_ok=True)

    # ---------------------------------------------------------------- what the updater remembers

    def restarted_for(self) -> str | None:
        try:
            return self.restarted_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def clear_restart_note(self) -> None:
        self.restarted_file.unlink(missing_ok=True)

    def note_restart(self, version: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=self.root, prefix=".part-", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(version)
            os.replace(temp, self.restarted_file)
        finally:
            Path(temp).unlink(missing_ok=True)

    def read_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def write_state(self, state: dict[str, Any]) -> None:
        self._write_json(self.state_file, state)

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".part-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            os.replace(temp, path)
        finally:
            Path(temp).unlink(missing_ok=True)


def image_version() -> str | None:
    """The yt-dlp the image was built with, read from its metadata (nothing is imported)."""
    try:
        return importlib.metadata.version(PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return None


def activate(store: ToolStore, *, image: str | None = None) -> Active | None:
    """At start, before anything imports yt_dlp: puts the stored newer copy first on the import path. Returns it, or `None` when the image's own
    copy is used (no pointer, a bad file, or the image is as new or newer, as after `encore update`)."""
    pointer = store.read_pointer()
    if pointer is None:
        if store.pointer_file.exists():
            store.clear_pointer()  # unreadable or pointing out of the folder; `read_pointer` said why
        return None
    image = image if image is not None else image_version()
    wanted, have = version_key(pointer.version), version_key(image or "")
    if wanted is None:
        log.warning(
            "yt-dlp: the pointer names the version %r, which is not a release; using the image's own copy", pointer.version
        )
        store.clear_pointer()
        return None
    if have is not None and wanted <= have:
        log.info(
            "yt-dlp: the image carries %s, which is not older than the stored %s; using the image's copy", image, pointer.version
        )
        store.clear_pointer()
        return None
    wheel = store.verified_wheel(pointer)
    if wheel is None:
        # Nothing may keep waiting for (and restarting for) a copy that cannot be used; the next daily check fetches the release again.
        store.clear_pointer()
        return None
    if "yt_dlp" in sys.modules:
        log.warning("yt-dlp: already imported before the stored copy could be put first; keeping the one in use")
        return None
    sys.path.insert(0, str(wheel))
    existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = str(wheel) + (os.pathsep + existing if existing else "")
    log.info("yt-dlp: running the stored copy %s (the image carries %s)", pointer.version, image)
    return Active(pointer.version, wheel)


def running_version(active: Active | None) -> str:
    return active.version if active is not None else (image_version() or "unknown")


# ---------------------------------------------------------------------------------------------------- what PyPI says


def newest_eligible(
    meta: dict[str, Any], *, now: float, above: tuple[int, ...], min_age_s: float = MIN_RELEASE_AGE_S, skip: Collection[str] = ()
) -> Release | None:
    """The newest release with a plain wheel that is older than [min_age_s], newer than [above], not yanked and not in [skip]."""
    best: tuple[tuple[int, ...], Release] | None = None
    releases = meta.get("releases")
    if not isinstance(releases, dict):
        return None
    for version, files in releases.items():
        key = version_key(version)
        if key is None or key <= above or version in skip or not isinstance(files, list):
            continue
        for file in files:
            if (
                not isinstance(file, dict)
                or file.get("yanked")
                or not str(file.get("filename", "")).endswith("-py3-none-any.whl")
            ):
                continue
            try:
                uploaded = datetime.fromisoformat(str(file["upload_time_iso_8601"]).replace("Z", "+00:00")).timestamp()
                release = Release(version, str(file["filename"]), str(file["url"]), str(file["digests"]["sha256"]), uploaded)
            except (KeyError, TypeError, ValueError):
                continue
            if now - uploaded < min_age_s:
                continue
            if best is None or key > best[0]:
                best = (key, release)
    return best[1] if best else None
