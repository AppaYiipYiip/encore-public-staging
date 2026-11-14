"""`GET /encore/stream/{ref}` (docs/04 section 4): a song's audio passed on from YouTube, with Range, behind a signed address."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from encore_server import refs
from encore_server.api import create_app
from encore_server.auth import sign_stream
from encore_server.config import Settings
from encore_server.sources.youtube.errors import DownloadError
from encore_server.sources.youtube.lean import LeanResolver
from encore_server.sources.youtube.source import Wanted, YoutubeSource
from encore_server.sources.youtube.stream import StreamError, StreamProxy
from tests.conftest import FakeVerifier, creds, resolve, song
from tests.sources.test_stream import FakeYouTube, info_file

V1 = "/encore/api/v1"
DATA = bytes(range(256)) * 9000  # a bit over two megabytes


class Source:
    """A YouTube source whose search is a list and whose bytes are FakeYouTube's."""

    def __init__(self, tmp: Path, *, found=None, extract=None):  # type: ignore[no-untyped-def]
        self.asked: list[Wanted] = []
        self.remembered: list[tuple[str, str]] = []
        self.youtube = FakeYouTube(DATA)

        def candidates(wanted: Wanted) -> list[tuple[str, str, int | None]]:
            self.asked.append(wanted)
            return found if found is not None else [("aaaaaaaaaaa", wanted.title, 318)]

        self.source = YoutubeSource(
            tmp,
            proxy=StreamProxy(
                candidates=candidates,
                extract=extract or info_file(size=len(DATA)),
                work_dir=tmp,
                opener=self.youtube,
                sleep=lambda s: None,
            ),
        )

    def open(self, wanted: Wanted, range_header: str | None):  # type: ignore[no-untyped-def]
        return self.source.open(wanted, range_header)


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier):  # type: ignore[no-untyped-def]
    source = Source(tmp_path / "work")
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, youtube=source)) as client:  # type: ignore[arg-type]
        yield client, source


def address(client: TestClient, ref: str, user: str = "marwa") -> str:
    response = client.get(f"{V1}/refs/{ref}/stream-url", params=creds(user))
    assert response.status_code == 200, response.text
    return response.json()["url"]  # type: ignore[no-any-return]


def test_the_address_is_signed_and_plays_the_song(rig) -> None:  # type: ignore[no-untyped-def]
    client, source = rig
    ref = resolve(client, "marwa", song())[0]["id"]

    response = client.get(address(client, str(ref)))

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/webm" and response.headers["accept-ranges"] == "bytes"
    assert response.content == DATA
    assert source.asked[0].title == "Weird Fishes / Arpeggi" and source.asked[0].artist == "Radiohead"


def test_a_seek_is_a_206_with_the_range_asked_for(rig) -> None:  # type: ignore[no-untyped-def]
    client, _ = rig
    ref = resolve(client, "marwa", song())[0]["id"]

    response = client.get(address(client, str(ref)), headers={"Range": "bytes=1000-1999"})

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 1000-1999/{len(DATA)}"
    assert response.content == DATA[1000:2000]


def test_a_head_request_gets_the_headers_only(rig) -> None:  # type: ignore[no-untyped-def]
    client, _ = rig
    ref = resolve(client, "marwa", song())[0]["id"]

    response = client.head(address(client, str(ref)))

    assert response.status_code == 200 and response.content == b""
    assert response.headers["content-length"] == str(len(DATA))


def test_no_login_is_needed_with_a_good_address_and_none_works_without_one(rig) -> None:  # type: ignore[no-untyped-def]
    client, _ = rig
    ref = str(resolve(client, "marwa", song())[0]["id"])
    url = address(client, ref)

    assert client.get(url).status_code == 200
    assert client.get(f"/encore/stream/{ref}").status_code == 401


@pytest.mark.parametrize("change", ["sig", "ref", "person", "expiry"])
def test_an_address_that_was_changed_is_refused(rig, change: str) -> None:  # type: ignore[no-untyped-def]
    client, _ = rig
    ref, other = (str(r["id"]) for r in resolve(client, "marwa", song(), song("Reckoner")))
    path, _, query = address(client, ref).partition("?")
    params = dict(part.split("=") for part in query.split("&"))
    if change == "sig":
        params["sig"] = "0" * 32
    elif change == "person":
        params["p"] = "pn_" + "0" * 26
    elif change == "expiry":
        params["e"] = str(int(params["e"]) + 3600)
    elif change == "ref":
        path = f"/encore/stream/{other}"

    response = client.get(path, params=params)

    assert response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"


def test_an_address_that_has_expired_says_to_play_the_song_again(rig) -> None:  # type: ignore[no-untyped-def]
    client, _ = rig
    ref = str(resolve(client, "marwa", song())[0]["id"])
    person = client.get(f"{V1}/me", params=creds("marwa")).json()["id"]
    from encore_server.auth import stream_secret

    with client.app.state.services.db.tx() as conn:  # type: ignore[attr-defined]
        secret = stream_secret(conn)
    expired = int(time.time()) - 5
    sig = sign_stream(secret, person, ref, expired)

    response = client.get(f"/encore/stream/{ref}", params={"p": person, "e": expired, "sig": sig})

    assert response.status_code == 401 and "expired" in response.json()["error"]["message"]


def test_the_address_of_a_song_nobody_knows_is_not_found(rig) -> None:  # type: ignore[no-untyped-def]
    client, _ = rig
    response = client.get(f"{V1}/refs/sr_00000000000000000000000000/stream-url", params=creds("marwa"))
    assert response.status_code == 404


def test_the_address_needs_a_login(rig) -> None:  # type: ignore[no-untyped-def]
    client, _ = rig
    ref = str(resolve(client, "marwa", song())[0]["id"])
    assert client.get(f"{V1}/refs/{ref}/stream-url").status_code == 401


def test_a_song_whose_video_is_known_is_not_searched_for(rig) -> None:  # type: ignore[no-untyped-def]
    client, source = rig
    ref = resolve(client, "marwa", song(videoId="bgsmr7t8zGE"))[0]["id"]

    client.get(address(client, str(ref)))

    assert source.asked[0].video_id == "bgsmr7t8zGE"


@pytest.mark.parametrize(
    ("code", "status", "error", "reason"),
    [
        ("age_restricted", 404, "song_unavailable", "age_restricted"),
        ("unavailable", 404, "song_unavailable", "removed"),
        ("blocked", 503, "source_busy", None),
    ],
)
def test_what_goes_wrong_is_one_error_with_words(
    tmp_path: Path, verifier: FakeVerifier, code: str, status: int, error: str, reason: str | None
) -> None:
    """PB-13, PB-14: a removed song and an age check each answer 404 song_unavailable with their own reason."""

    def extract(video_id: str, path: Path) -> None:
        raise DownloadError(code)

    source = Source(tmp_path / "work", extract=extract)
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, youtube=source)) as client:  # type: ignore[arg-type]
        ref = str(resolve(client, "marwa", song())[0]["id"])
        response = client.get(address(client, ref))

    assert response.status_code == status
    body = response.json()["error"]
    assert body["code"] == error and body["message"]
    assert body["details"].get("reason") == reason


def test_a_song_nothing_matches_is_song_unavailable(tmp_path: Path, verifier: FakeVerifier) -> None:
    """PB-12: a song YouTube does not have answers 404 song_unavailable, reason not_found."""
    source = Source(tmp_path / "work", found=[])
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, youtube=source)) as client:  # type: ignore[arg-type]
        ref = str(resolve(client, "marwa", song())[0]["id"])
        response = client.get(address(client, ref))

    assert response.status_code == 404 and response.json()["error"]["details"]["reason"] == "not_found"


def test_a_search_that_failed_is_a_retryable_502_and_never_a_missing_song(tmp_path: Path, verifier: FakeVerifier) -> None:
    """B-122: the search service timing out or being down said nothing about the song, yet it was answered 404 `song_unavailable` (reason `removed`,
    `retryable: false`), which the app takes as final and which the server may one day remember. It is a 502 `source_unreachable`, retryable, with no
    reason about the song. The whole path is real: the route, the source, the proxy and the resolver, with only the search service broken."""

    class BrokenSearch:
        def songs(self, query: str, limit: int) -> list[dict]:
            raise OSError("the search service is not answering")

        videos = songs

    resolver = LeanResolver(BrokenSearch(), max_duration_s=6 * 3600)
    source = YoutubeSource(tmp_path / "work", resolver=resolver, extractor=object())
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, youtube=source)) as client:  # type: ignore[arg-type]
        ref = str(resolve(client, "marwa", song())[0]["id"])
        response = client.get(address(client, ref))

    body = response.json()["error"]
    assert response.status_code == 502 and body["code"] == "source_unreachable" and body["retryable"] is True
    assert "reason" not in (body.get("details") or {})


def test_a_slow_start_is_a_504_with_a_sentence(tmp_path: Path, verifier: FakeVerifier) -> None:
    class Slow:
        def open(self, wanted: Wanted, range_header: str | None):  # type: ignore[no-untyped-def]
            raise StreamError("slow")

    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, youtube=Slow())) as client:  # type: ignore[arg-type]
        ref = str(resolve(client, "marwa", song())[0]["id"])
        response = client.get(address(client, ref))

    assert response.status_code == 504
    body = response.json()["error"]
    assert body["code"] == "upstream_timeout" and body["retryable"] is True


def test_any_other_failure_is_one_plain_sentence(tmp_path: Path, verifier: FakeVerifier) -> None:
    """PB-17: a failure nobody planned for answers 502 source_unreachable with one plain sentence, never the raw error."""

    def extract(video_id: str, path: Path) -> None:
        raise DownloadError("a_failure_nobody_planned_for")

    source = Source(tmp_path / "work", extract=extract)
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, youtube=source)) as client:  # type: ignore[arg-type]
        ref = str(resolve(client, "marwa", song())[0]["id"])
        response = client.get(address(client, ref))

    assert response.status_code == 502
    body = response.json()["error"]
    assert body["code"] == "source_unreachable" and body["message"] == "The song could not be fetched. Try again."
    assert "nobody_planned_for" not in response.text, "the raw failure never reaches the phone"


def test_a_server_without_youtube_says_so(client: TestClient) -> None:
    """PB-18: a server with no YouTube (switched off, or its libraries missing) says so in one sentence."""
    ref = str(resolve(client, "marwa", song())[0]["id"])
    response = client.get(address(client, ref))
    assert response.status_code == 502 and response.json()["error"]["code"] == "source_unreachable"
    assert response.json()["error"]["message"] == "This server cannot fetch songs from YouTube."


class GoneFromTheMusicServer:
    """A music server that is set up and answers but no longer has the kept file: to `open_stream` that is the same as a missing song."""

    configured = True

    def __init__(self) -> None:
        self.asked: list[str] = []

    def open_stream(self, song_id: str, range_header: str | None, **_: object) -> None:
        self.asked.append(song_id)


def keep_a_file(client: TestClient, ref: str) -> None:
    with client.app.state.services.db.tx() as conn:  # type: ignore[attr-defined]
        refs.attach_file(conn, ref, navidrome_song_id="nd-1", path="a.opus", codec="opus", bitrate_kbps=130, source="youtube")


def test_a_kept_song_whose_file_is_gone_streams_from_youtube_again(rig) -> None:  # type: ignore[no-untyped-def]
    """CF-31, PB-3: the file is gone from the music server but a person uses the song: the row stays and it streams from YouTube again."""
    client, source = rig
    ref = str(resolve(client, "marwa", song())[0]["id"])
    keep_a_file(client, ref)
    music = GoneFromTheMusicServer()
    client.app.state.services.music = music  # type: ignore[attr-defined]

    response = client.get(address(client, ref))

    assert music.asked == ["nd-1"], "the kept file was tried first"
    assert response.status_code == 200 and response.content == DATA, "and YouTube served the song when the file was gone"
    assert source.asked, "YouTube was asked for the song"
    with client.app.state.services.db.read() as conn:  # type: ignore[attr-defined]
        assert refs.get_ref(conn, ref)["id"] == ref, "the song is still in the library"


def test_a_kept_song_whose_file_is_gone_and_that_youtube_does_not_have_says_it_cannot_play(
    tmp_path: Path, verifier: FakeVerifier
) -> None:
    """CF-31, PB-8: the file is gone from the music server and nothing matches on YouTube either: a sentence, and the song stays."""
    source = Source(tmp_path / "work", found=[])
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, youtube=source)) as client:  # type: ignore[arg-type]
        ref = str(resolve(client, "marwa", song())[0]["id"])
        keep_a_file(client, ref)
        client.app.state.services.music = GoneFromTheMusicServer()  # type: ignore[attr-defined]

        response = client.get(address(client, ref))

        with client.app.state.services.db.read() as conn:  # type: ignore[attr-defined]
            assert refs.get_ref(conn, ref)["id"] == ref, "the song is still in the library"

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "song_unavailable" and error["message"] and error["details"]["reason"] == "not_found"
