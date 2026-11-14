"""Bringing a person's library over from the music server (docs/18 section 4, docs/tasks P2-11).

Before the Encore server, a person's likes and playlists lived in the music server (Navidrome) as stars and playlists. This reads them *as the
person* (with the sign-in the phone sends along: the Encore server has no password to use) and gives them refs, likes and playlists here.

Safe to run again and from a second phone: a like is a set, and a playlist is made once per source playlist (`playlist.source_id`
`nd:<id>`); a playlist that already has songs is not filled again.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from . import library, refs
from .db import Database
from .errors import ApiError
from .ids import new_id
from .navidrome import file_meta
from .scanner import described

log = logging.getLogger("encore_server.migration")

MAX_PLAYLISTS = 2000


class SubsonicUser:
    """The music server asked as one person (their token and salt), for what that person has there."""

    def __init__(self, base_url: str, user: str, token: str, salt: str, *, client: httpx.Client | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._auth = {"u": user, "t": token, "s": salt, "v": "1.16.1", "c": "encore-server", "f": "json"}
        self._client = client or httpx.Client(timeout=30.0)

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        try:
            response = self._client.get(
                f"{self._base}/rest/{method}.view", params={**self._auth, **{k: str(v) for k, v in params.items()}}
            )
            body = response.json().get("subsonic-response", {})
        except (httpx.HTTPError, ValueError) as error:
            raise ApiError("server_busy", "The music server is not answering.") from error
        if body.get("status") != "ok":
            raise ApiError("unauthorized", "The music server did not accept that login.")
        return body  # type: ignore[no-any-return]


def _list(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _epoch_ms(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.replace(tzinfo=parsed.tzinfo or UTC).timestamp() * 1000)


def _ref_for_song(conn: Any, song: dict[str, Any]) -> str | None:
    """The ref of a song of the music server: the one its file is attached to, else made from what the song says (and its file attached)."""
    song_id = str(song.get("id") or "")
    if not song_id:
        return None
    row = refs.file_holders(conn, [song_id]).get(song_id)
    if row is not None:
        return str(row["ref"])
    item = described(song)
    if item is None:
        return None
    try:
        ref = refs.resolve(conn, item)
    except ApiError:
        return None
    suffix = str(song.get("suffix") or "").lower()
    refs.attach_file(
        conn,
        ref["id"],
        navidrome_song_id=song_id,
        path=str(song.get("path") or "") or None,
        codec={"opus": "opus", "ogg": "opus", "m4a": "aac", "aac": "aac", "mp3": "mp3", "flac": "flac"}.get(
            suffix, suffix or None
        ),
        bitrate_kbps=song.get("bitRate") if isinstance(song.get("bitRate"), int) else None,
        source="library",
        meta=file_meta(song),
    )
    return str(ref["id"])


def migrate_from_navidrome(db: Database, person_id: str, user: str, music: SubsonicUser) -> dict[str, int]:
    """Likes, saved albums, followed artists and playlists of [user] in the music server become the person's here."""
    report = {"likes": 0, "albums": 0, "artists": 0, "playlists": 0, "entries": 0, "unmatched": 0}

    starred = music.call("getStarred2").get("starred2") or {}
    with db.tx() as conn:
        for song in _list(starred.get("song")):
            ref = _ref_for_song(conn, song)
            if ref is None:
                report["unmatched"] += 1
                continue
            if library.set_item(conn, person_id, "like", ref, at=_epoch_ms(song.get("starred"))):
                report["likes"] += 1
        for album in _list(starred.get("album")):
            if album.get("id") and library.set_item(
                conn, person_id, "saved_album", str(album["id"])[:100], at=_epoch_ms(album.get("starred"))
            ):
                report["albums"] += 1
        for artist in _list(starred.get("artist")):
            if artist.get("id") and library.set_item(
                conn, person_id, "follow_artist", str(artist["id"])[:100], at=_epoch_ms(artist.get("starred"))
            ):
                report["artists"] += 1

    lists = _list(music.call("getPlaylists").get("playlists", {}).get("playlist"))
    mine = [p for p in lists if str(p.get("owner") or user).lower() == user.lower() and not p.get("readonly")][:MAX_PLAYLISTS]
    for summary in mine:
        source_id = f"nd:{summary.get('id')}"
        detail = music.call("getPlaylist", id=summary["id"]).get("playlist") or {}
        songs = _list(detail.get("entry"))
        with db.tx() as conn:
            existing = conn.execute(
                "SELECT id FROM playlist WHERE owner = ? AND source_id = ?", (person_id, source_id)
            ).fetchone()
            if existing is not None:
                playlist_id = existing["id"]
            else:
                playlist_id = new_id("pl")
                row = library.create_playlist(conn, person_id, playlist_id, summary.get("name") or "Playlist")
                conn.execute(
                    "UPDATE playlist SET source_id = ?, created_at = COALESCE(?, created_at) WHERE id = ?",
                    (source_id, _epoch_ms(summary.get("created")), row["id"]),
                )
                report["playlists"] += 1
            filled = (
                conn.execute("SELECT 1 FROM playlist_entry WHERE playlist = ? LIMIT 1", (playlist_id,)).fetchone() is not None
            )
            if filled:
                continue  # an earlier run (or another phone) already brought its songs
            wanted: list[dict[str, str]] = []
            for song in songs:
                ref = _ref_for_song(conn, song)
                if ref is None:
                    report["unmatched"] += 1
                    continue
                wanted.append({"ref": ref})
            for start in range(0, len(wanted), library.MAX_ENTRIES_PER_CALL):
                library.add_entries(conn, person_id, playlist_id, wanted[start : start + library.MAX_ENTRIES_PER_CALL])
            report["entries"] += len(wanted)
    log.info("brought over %s's library: %s", user, report)
    return report
