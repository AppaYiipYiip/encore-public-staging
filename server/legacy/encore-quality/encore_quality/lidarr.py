"""What the quality tier asks of Lidarr, which is the one that knows MusicBrainz and files an album away properly.

Everything here was found by trying the real program (docs/46, results S3): the artist must be monitored (with "new items: none") for a
monitored album to be wanted at all, an album is marked wanted only after its artist's refresh has finished, and creating a folder or a
profile twice is an error, so the wiring looks before it creates.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

#: `(method, path below /api/v1, json body or None) -> (status, parsed JSON or None)`; the tests give a fake. Status 0: not reachable.
Http = Callable[[str, str, Any], "tuple[int, Any]"]


class LidarrError(Exception):
    """Lidarr said no or did not answer; the message is for the log, not for a person."""


def http_for(base_url: str, api_key: str, timeout: float = 60.0) -> Http:
    base = base_url.rstrip("/") + "/api/v1"

    def call(method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(base + path, data=data, method=method, headers={
            "X-Api-Key": api_key, "User-Agent": "encore-quality/1", **({"Content-Type": "application/json"} if data is not None else {})})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - the stack's own network
                raw = response.read(8_000_000)
                status = response.status
        except urllib.error.HTTPError as error:
            raw, status = error.read(200_000), error.code
        except (urllib.error.URLError, OSError, TimeoutError):
            return 0, None
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, None

    return call


class Lidarr:
    def __init__(self, http: Http) -> None:
        self._http = http

    def _get(self, path: str) -> Any:
        status, data = self._http("GET", path, None)
        if status != 200:
            raise LidarrError(f"GET {path} -> {status}")
        return data

    def _send(self, method: str, path: str, body: Any) -> Any:
        status, data = self._http(method, path, body)
        if status not in (200, 201, 202):
            raise LidarrError(f"{method} {path} -> {status}: {str(data)[:200]}")
        return data

    # ------------------------------------------------------------------ is it there

    def version(self) -> str | None:
        status, data = self._http("GET", "/system/status", None)
        return str(data.get("version")) if status == 200 and isinstance(data, dict) and data.get("version") else None

    # ------------------------------------------------------------------ the wiring (looked at before it is made)

    def root_folders(self) -> list[dict]:
        return self._get("/rootfolder") or []

    def add_root_folder(self, path: str, quality_id: int, metadata_id: int) -> dict:
        return self._send("POST", "/rootfolder", {
            "name": "Encore pool", "path": path, "defaultMetadataProfileId": metadata_id, "defaultQualityProfileId": quality_id,
            "defaultMonitorOption": "none", "defaultNewItemMonitorOption": "none", "defaultTags": []})

    def quality_profiles(self) -> list[dict]:
        return self._get("/qualityprofile") or []

    def quality_profile_schema(self) -> dict:
        return self._get("/qualityprofile/schema")

    def add_quality_profile(self, profile: dict) -> dict:
        return self._send("POST", "/qualityprofile", profile)

    def update_quality_profile(self, profile: dict) -> dict:
        return self._send("PUT", f"/qualityprofile/{profile['id']}", profile)

    def metadata_profiles(self) -> list[dict]:
        return self._get("/metadataprofile") or []

    def metadata_profile_schema(self) -> dict:
        return self._get("/metadataprofile/schema")

    def add_metadata_profile(self, profile: dict) -> dict:
        return self._send("POST", "/metadataprofile", profile)

    def update_metadata_profile(self, profile: dict) -> dict:
        return self._send("PUT", f"/metadataprofile/{profile['id']}", profile)

    def naming(self) -> dict:
        return self._get("/config/naming")

    def put_naming(self, config: dict) -> dict:
        return self._send("PUT", f"/config/naming/{config.get('id', 1)}", config)

    def media_management(self) -> dict:
        return self._get("/config/mediamanagement")

    def put_media_management(self, config: dict) -> dict:
        return self._send("PUT", f"/config/mediamanagement/{config.get('id', 1)}", config)

    # ------------------------------------------------------------------ finding and wanting an album

    def album_lookup(self, term: str) -> list[dict]:
        """MusicBrainz albums matching [term], as Lidarr's own metadata service knows them (can take several seconds)."""
        return self._get("/album/lookup?term=" + urllib.parse.quote(term)) or []

    def artists(self) -> list[dict]:
        return self._get("/artist") or []

    def add_artist(self, artist: dict, *, quality_id: int, metadata_id: int, root_path: str) -> dict:
        """Adds the artist **monitored** but with nothing wanted (`monitor: none`, `monitorNewItems: none`): Lidarr wants the discography
        of a monitored artist unless told otherwise, and an album is not wanted unless its artist is monitored."""
        body = dict(artist)
        body.update({"qualityProfileId": quality_id, "metadataProfileId": metadata_id, "rootFolderPath": root_path, "monitored": True,
                     "monitorNewItems": "none", "addOptions": {"monitor": "none", "searchForMissingAlbums": False}})
        return self._send("POST", "/artist", body)

    def ensure_artist_monitored(self, artist_id: int) -> None:
        """Lidarr only wants the albums of a *monitored* artist; marking the artist leaves what it wants (only what we mark) alone."""
        artist = self._get(f"/artist/{int(artist_id)}")
        if not artist.get("monitored"):
            self._send("PUT", f"/artist/{int(artist_id)}", {**artist, "monitored": True})

    def albums(self, artist_id: int) -> list[dict]:
        return self._get(f"/album?artistId={int(artist_id)}") or []

    def album(self, album_id: int) -> dict:
        return self._get(f"/album/{int(album_id)}")

    def monitor_albums(self, album_ids: list[int], monitored: bool) -> None:
        self._send("PUT", "/album/monitor", {"albumIds": [int(i) for i in album_ids], "monitored": monitored})

    def refreshing(self, artist_id: int) -> bool:
        """Whether Lidarr is still learning this artist's releases (minutes for a prolific artist)."""
        for command in self._get("/command") or []:
            if command.get("name") == "RefreshArtist" and command.get("status") in ("queued", "started"):
                body = command.get("body") or {}
                ids = body.get("artistIds") or ([body["artistId"]] if "artistId" in body else [])
                if not ids or int(artist_id) in [int(i) for i in ids]:
                    return True
        return False

    def tracks(self, album_id: int) -> list[dict]:
        return self._get(f"/track?albumId={int(album_id)}") or []

    def track_files(self, album_id: int) -> list[dict]:
        return self._get(f"/trackfile?albumId={int(album_id)}") or []
