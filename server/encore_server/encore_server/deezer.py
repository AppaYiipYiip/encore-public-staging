"""The one place the server asks the catalogue (Deezer's public search) which recordings match an artist and a title.

The cover finder (a song's album picture) and the artist finder (an artist's picture) both ask the same question, and both must tell the three
possible answers apart: **found**, **nothing there** (an empty list: the catalogue knows no such recording) and **could not ask** (it timed out,
refused, was throttled, or answered something that is not an answer). Only the second is a fact worth remembering for a week; the third is not
(audit B-124: an outage used to be stored as "nothing found" and the song was left alone for a week).
"""

from __future__ import annotations

from typing import Any

import httpx

SEARCH_URL = "https://api.deezer.com/search"

#: The address shape Deezer gives an artist that has no picture of its own: any host serves the same grey silhouette (an empty image id).
#: It is a picture of nobody; it must never be chosen, and must be dropped *before* choosing between namesakes.
PLACEHOLDER_ARTIST_PICTURE = "/images/artist//"


class LookupUnavailable(Exception):
    """The catalogue could not be asked just now. Not an answer: nothing may be remembered about the song or the artist because of it."""


def search_tracks(artist: str, title: str, *, client: httpx.Client | None = None, limit: int = 8) -> list[dict[str, Any]]:
    """The recordings the catalogue lists for "artist title" (a plain search: its field search finds nothing for many real songs), best first.

    An empty list means the catalogue answered and knows none. [LookupUnavailable] means it did not answer in a way that can be trusted."""
    own = client is None
    http = client or httpx.Client(timeout=8.0, headers={"User-Agent": "encore-server/1"})
    try:
        response = http.get(SEARCH_URL, params={"q": f"{artist} {title}", "limit": limit})
        if response.status_code != 200:
            raise LookupUnavailable(f"HTTP {response.status_code}")
        body = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise LookupUnavailable(type(error).__name__) from error
    finally:
        if own:
            http.close()
    # A throttled request still answers 200, with an error in the body: that is "could not ask", not "nothing found".
    if not isinstance(body, dict) or "error" in body or not isinstance(body.get("data"), list):
        raise LookupUnavailable("an answer that is not a list of recordings")
    return [hit for hit in body["data"] if isinstance(hit, dict)]
