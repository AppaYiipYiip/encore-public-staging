"""Putting Lidarr and Soularr in the state the quality tier needs, and keeping them there.

Idempotent on purpose: it runs at every start and again every few minutes, so a server whose Lidarr was reset, restored from a backup or
fiddled with by a curious owner finds its way back, and nothing is created twice (Lidarr answers an error for a duplicate).
"""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .lidarr import Lidarr, LidarrError

log = logging.getLogger("encore_quality.wiring")

NAME = "Encore"
#: Lidarr's quality ids: FLAC, FLAC 24bit, MP3-320, MP3-VBR-V0. Everything below these is refused: a 128 kbps file is what the quick copy is.
ACCEPTED = {6: "FLAC", 21: "FLAC 24bit", 4: "MP3-320", 2: "MP3-VBR-V0"}
CUTOFF = 6  # FLAC: Lidarr keeps looking for better until it has this


@dataclass(frozen=True)
class Wiring:
    quality_id: int
    metadata_id: int
    pool: str


def ensure_lidarr(lidarr: Lidarr, pool: str) -> Wiring:
    quality_id = _ensure_quality_profile(lidarr)
    metadata_id = _ensure_metadata_profile(lidarr)
    if not any(str(folder.get("path", "")).rstrip("/") == pool.rstrip("/") for folder in lidarr.root_folders()):
        lidarr.add_root_folder(pool, quality_id, metadata_id)
        log.info("Lidarr now files into %s", pool)
    naming = lidarr.naming()
    if not naming.get("renameTracks"):
        # Without renaming Lidarr keeps the file name and drops the album folder: two albums that both have "01 - Intro.flac" would collide.
        lidarr.put_naming({**naming, "renameTracks": True})
    media = lidarr.media_management()
    if not media.get("copyUsingHardlinks"):
        lidarr.put_media_management({**media, "copyUsingHardlinks": True})
    return Wiring(quality_id, metadata_id, pool)


def _ensure_quality_profile(lidarr: Lidarr) -> int:
    schema = lidarr.quality_profile_schema()
    leaves = []
    for item in schema.get("items", []):
        for leaf in (item["items"] if item.get("items") else [item]):
            leaves.append({"quality": leaf["quality"], "items": [], "allowed": leaf["quality"]["id"] in ACCEPTED})
    wanted = {**schema, "name": NAME, "upgradeAllowed": True, "cutoff": CUTOFF, "items": leaves}
    for profile in lidarr.quality_profiles():
        if profile.get("name") != NAME:
            continue
        have = {leaf["quality"]["id"] for leaf in _leaves(profile) if leaf.get("allowed")}
        if have != set(ACCEPTED) or profile.get("cutoff") != CUTOFF or not profile.get("upgradeAllowed"):
            lidarr.update_quality_profile({**wanted, "id": profile["id"]})
        return int(profile["id"])
    return int(lidarr.add_quality_profile(wanted)["id"])


def _leaves(profile: dict) -> list[dict]:
    out = []
    for item in profile.get("items", []):
        out.extend(item["items"] if item.get("items") else [item])
    return out


def _ensure_metadata_profile(lidarr: Lidarr) -> int:
    """Every kind of release is allowed: Lidarr's own "Standard" hides singles, EPs and live albums, and a song a person plays can be on
    any of them. Which one is right is decided by matching (matching.py), not by hiding the others."""
    schema = lidarr.metadata_profile_schema()
    for kind in schema.get("primaryAlbumTypes", []) + schema.get("secondaryAlbumTypes", []):
        kind["allowed"] = True
    for status in schema.get("releaseStatuses", []):
        status["allowed"] = status["releaseStatus"]["name"] in ("Official", "Promotion")
    wanted = {**schema, "name": NAME}
    for profile in lidarr.metadata_profiles():
        if profile.get("name") == NAME:
            if not all(k.get("allowed") for k in profile.get("primaryAlbumTypes", []) + profile.get("secondaryAlbumTypes", [])):
                lidarr.update_metadata_profile({**wanted, "id": profile["id"]})
            return int(profile["id"])
    return int(lidarr.add_metadata_profile(wanted)["id"])


# ---------------------------------------------------------------------------------------------------------------- Soularr

#: FLAC at the usual depths, then MP3 at exactly 320 (Soularr compares the bitrate as a number, so it cannot ask for "V0").
FILETYPES = "flac 24/192,flac 24/96,flac 24/48,flac 16/44.1,flac,mp3 320"

SOULARR_TEMPLATE = """[Lidarr]
api_key = {lidarr_key}
host_url = {lidarr_url}
download_dir = {downloads}
disable_sync = False

[Slskd]
api_key = {slskd_key}
host_url = {slskd_url}
url_base = /
download_dir = {downloads}
delete_searches = True
stalled_timeout = 3600
remote_queue_timeout = 300

[Release Settings]
use_selected_lidarr_release = False
use_most_common_tracknum = True
allow_multi_disc = True
accepted_countries = Europe,Japan,United Kingdom,United States,[Worldwide],Australia,Canada
skip_region_check = False
accepted_formats = CD,Digital Media,Vinyl

[Search Settings]
search_timeout = 5000
maximum_peer_queue = 50
minimum_peer_upload_speed = 0
minimum_filename_match_ratio = 0.8
minimum_search_interval = 5
allowed_filetypes = {filetypes}
ignored_users =
album_prepend_artist = False
search_type = incrementing_page
number_of_albums_to_grab = 10
title_blacklist =
search_blacklist =
search_source = missing
failed_import_denylist = True

[Download Settings]
download_filtering = True
use_extension_whitelist = False
extensions_whitelist = lrc,nfo,txt
rename_download_folders = True

[Logging]
level = INFO
format = [%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s
datefmt = %Y-%m-%dT%H:%M:%S%z
"""


def render_soularr(*, lidarr_key: str, lidarr_url: str, slskd_key: str, slskd_url: str, downloads: str) -> str:
    """Soularr's `config.ini`. Both programs see the downloads at the same path (the whole stack shares one mount, docs/46 S2)."""
    return SOULARR_TEMPLATE.format(lidarr_key=lidarr_key, lidarr_url=lidarr_url, slskd_key=slskd_key, slskd_url=slskd_url,
                                   downloads=downloads, filetypes=FILETYPES)


def write_if_changed(path: Path, text: str) -> bool:
    """Writes [text] to [path] atomically and only when it differs (Soularr re-reads it at each run; an untouched file stays untouched)."""
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o600)  # it holds the two program keys
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


__all__ = ["Wiring", "ensure_lidarr", "render_soularr", "write_if_changed", "LidarrError", "ACCEPTED", "NAME"]
