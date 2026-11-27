"""PROBE (to be replaced by the real tests of the real-path item): what Navidrome's own (native) API says about where a song's file lies.

The finding on N-38 (27 Nov 2026): the `path` the music server's Subsonic API reports for a song is built from its TAGS, not where the file lies. The music server has a setting that reports real paths
(`Subsonic.DefaultReportRealPath`, off by default, global and a security trade-off), which the server cannot count on in a stranger's own music server. The question here is whether its NATIVE API
(the one the server already signs in to as the administrator, `navidrome_admin.py`) gives the real location, and in what shape: one song, a list, a list by ids. This test fails on purpose to print the
answers into the CI log; it asserts nothing about them.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import pytest

from encore_server.navidrome import NavidromeClient
from encore_server.navidrome_admin import NavidromeAdmin
from tests.integration.conftest import MUSIC, URL, Rig, make_audio, scan_and_wait

pytestmark = pytest.mark.integration


def test_probe_what_the_native_api_says_about_where_a_file_lies(
    rig: Rig, navidrome: NavidromeClient, accounts: dict[str, str]
) -> None:
    unique = secrets.token_hex(3)
    artist, album = f"Zxqv Artist {unique}", f"Zxqv Album {unique}"
    elsewhere = make_audio(
        MUSIC / f"Zxqv misc {unique}" / "random-name-1234.opus", title=f"Zxqv Elsewhere {unique}", artist=artist, album=album
    )
    placed = make_audio(
        MUSIC / artist / album / f"Zxqv Placed {unique}.opus", title=f"Zxqv Placed {unique}", artist=artist, album=album
    )
    scan_and_wait(navidrome)

    found: dict[str, Any] = {
        "elsewhere_really_at": elsewhere.relative_to(MUSIC).as_posix(),
        "placed_really_at": placed.relative_to(MUSIC).as_posix(),
    }
    songs = (navidrome._call("search3", query="Zxqv", songCount=20, artistCount=0, albumCount=0) or {}).get(
        "searchResult3", {}
    ).get("song") or []
    ours = [s for s in songs if unique in str(s.get("title"))]
    found["subsonic"] = [{k: s.get(k) for k in ("id", "title", "path", "size")} for s in ours]

    admin = NavidromeAdmin(URL, accounts["admin"], accounts["admin_pw"])
    ids = [str(s["id"]) for s in ours]
    for name, route in (
        ("one", f"/api/song/{ids[0]}"),
        ("list_by_ids", "/api/song?" + "&".join(f"id={i}" for i in ids)),
        ("list_sorted", "/api/song?_start=0&_end=5&_sort=title&_order=ASC"),
        ("libraries", "/api/library"),
    ):
        try:
            body = admin.call("GET", route)
            if isinstance(body, list):
                found[name] = {
                    "count": len(body),
                    "first_keys": sorted(body[0].keys()) if body else [],
                    "paths": [
                        {k: s.get(k) for k in ("id", "title", "path", "libraryPath", "libraryId", "size")} for s in body[:4]
                    ],
                }
            else:
                found[name] = {
                    "keys": sorted(body.keys()),
                    "values": {k: body.get(k) for k in ("id", "title", "path", "libraryPath", "libraryId", "size", "name")},
                }
        except Exception as error:  # noqa: BLE001 - a probe prints what it meets
            found[name] = f"ERROR {type(error).__name__}: {error}"
    pytest.fail("RP_PROBE_BEGIN\n" + json.dumps(found, indent=1, default=str) + "\nRP_PROBE_END")
