"""The bytes: a picture from the music server and the audio of a song, behind signed addresses (docs/17 section 3)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import iterate_in_threadpool

from .. import (
    refs,
)
from ..auth import (
    COVER_PASS_SCOPE,
    person_may_listen,
    valid_stream_signature,
)
from ..errors import ApiError
from ..sources.youtube.errors import DownloadError
from ..sources.youtube.source import wanted_from_ref
from ..sources.youtube.stream import StreamError
from .common import _COVER_ID, services

log = logging.getLogger("encore_server.api")


def cover(cover_id: str, request: Request) -> Response:
    """`GET /encore/cover/{id}`: a picture from the music server, behind a signed address."""
    svc = services(request)
    query = request.query_params
    secret = svc.stream_key
    try:
        expires = int(query.get("e", "0"))
        size = int(query["size"]) if query.get("size") else None
    except ValueError:
        raise ApiError("validation", "That address is not right.") from None
    person, sig = query.get("p", ""), query.get("sig", "")
    with svc.db.read() as conn:
        still_here = person_may_listen(conn, person)
    if (
        not still_here
        or not _COVER_ID.match(cover_id)
        or not (
            valid_stream_signature(secret, person, f"cover:{cover_id}", expires, sig)
            or valid_stream_signature(secret, person, COVER_PASS_SCOPE, expires, sig)
        )
    ):
        raise ApiError("unauthorized", "This picture address has expired. Ask the app for it again.")
    if size is not None and not 16 <= size <= 2000:
        raise ApiError("validation", "A picture is asked for between 16 and 2000 pixels.")
    found = svc.music.cover(cover_id, size) if svc.music is not None and svc.music.configured else None
    if found is None:
        raise ApiError("not_found", "There is no such picture.")
    content, kind = found
    return Response(
        content=content if request.method != "HEAD" else b"", media_type=kind, headers={"Cache-Control": "private, max-age=86400"}
    )


_UNAVAILABLE_REASON = {"not_found": "not_found", "unavailable": "removed", "age_restricted": "age_restricted"}


def _stream_error(error: StreamError, youtube: Any = None) -> ApiError:
    if error.code in _UNAVAILABLE_REASON:
        return ApiError("song_unavailable", error.message, details={"reason": _UNAVAILABLE_REASON[error.code]})
    if error.code == "blocked":
        left = youtube.resting_for() if youtube is not None and hasattr(youtube, "resting_for") else 0
        return ApiError("source_busy", error.message, retry_after_ms=int(left * 1000) or None)
    if error.code == "slow":
        return ApiError("upstream_timeout", error.message)
    return ApiError("source_unreachable", error.message)


def stream(ref_id: str, request: Request) -> StreamingResponse:
    """`GET /encore/stream/{ref}`: the song's audio from YouTube, passed on as it arrives, with Range (docs/04 section 4)."""
    svc = services(request)
    query = request.query_params
    with svc.db.read() as conn:
        secret = svc.stream_key
        person = query.get("p", "")
        try:
            expires = int(query.get("e", "0"))
        except ValueError:
            expires = 0
        if not valid_stream_signature(secret, person, ref_id, expires, query.get("sig", "")) or not person_may_listen(
            conn, person
        ):
            raise ApiError("unauthorized", "This song address has expired. Ask the app to play it again.")
        ref = refs.get_ref(conn, ref_id)
    # The server decides where the audio comes from: its own copy when it keeps one (as its own account at the music server, `Range` and all),
    # YouTube otherwise. The phone asks for the same address either way (docs/tasks P2-20).
    kept = (ref.get("file") or {}).get("navidromeSongId")
    if kept and svc.music is not None and svc.music.configured:
        own = svc.music.open_stream(
            str(kept),
            request.headers.get("range"),
            max_bit_rate=_bit_rate(query.get("maxBitRate")),
            fmt=_audio_format(query.get("format")),
            estimate_length=_flag(query.get("estimateContentLength")),
        )
        if own is not None:
            return _pass_on(own, request)
    if svc.youtube is None:
        raise ApiError("source_unreachable", "This server cannot fetch songs from YouTube.")
    try:
        upstream = svc.youtube.open(wanted_from_ref(ref), request.headers.get("range"))
    except StreamError as error:
        raise _stream_error(error, svc.youtube) from error
    except DownloadError as error:
        raise _stream_error(StreamError(error.code), svc.youtube) from error
    return _pass_on(upstream, request)


def _pass_on(upstream: Any, request: Request) -> StreamingResponse:
    headers = {**upstream.headers, "Cache-Control": "no-store"}
    body = iterate_in_threadpool(upstream.body) if request.method != "HEAD" else iter(())
    if request.method == "HEAD":
        upstream.close()
    return StreamingResponse(
        body, status_code=upstream.status, headers=headers, media_type=headers.pop("Content-Type", None), background=None
    )


_BIT_RATES = frozenset({0, 32, 48, 64, 96, 112, 128, 160, 192, 224, 256, 320})
_FORMATS = frozenset({"mp3", "opus", "aac", "raw"})


def _bit_rate(value: str | None) -> int | None:
    """The quality cap a phone asks for (the setting for its network): one of the usual rates, or an error in words."""
    if value is None or value == "":
        return None
    if not value.isdigit() or int(value) not in _BIT_RATES:
        raise ApiError("validation", "That is not a quality this server offers.")
    return int(value) or None


def _flag(value: str | None) -> bool:
    """A download asking for the length of a transcoded song up front (so its progress can be shown): `true`, or nothing."""
    if value is None or value == "":
        return False
    if value != "true":
        raise ApiError("validation", "That is not something this server understands.")
    return True


def _audio_format(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if value not in _FORMATS:
        raise ApiError("validation", "That is not an audio format this server offers.")
    return None if value == "raw" else value
