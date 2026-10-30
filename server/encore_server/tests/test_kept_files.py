"""A phone needs only its device and a signed address: a kept song and a cover come from the music server through the Encore server's own account
(docs/tasks P2-20, docs/11 ADR-R40 prerequisite). The person's music-server login is never needed and never forwarded."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server import refs
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.navidrome import NavidromeClient
from tests.conftest import FakeVerifier, creds, resolve, song
from tests.test_stream_route import DATA, Source

V1 = "/encore/api/v1"
AUDIO = bytes(range(256)) * 400  # 100 kB of "mp3"
PICTURE = b"\xff\xd8\xff\xe0 pretend this is a jpeg " * 20


def streamed(data: bytes) -> Iterator[bytes]:
    """The body as a real response has it: a stream read once, in pieces (a bytes body would arrive already read)."""
    return iter([data[i : i + 8192] for i in range(0, len(data), 8192)])


class MusicServer:
    """What the music server does for the Encore server's own account: streams, pictures, and the text answers it gives for things it does not have."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.has_song = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        query = dict(request.url.params)
        if query.get("u") != "admin":
            return httpx.Response(200, headers={"content-type": "text/xml"}, content=b"<subsonic-response status='failed'/>")
        if request.url.path.endswith("/stream.view"):
            if not self.has_song or query.get("id") != "nd-42":
                return httpx.Response(200, headers={"content-type": "text/xml"}, content=b"<subsonic-response status='failed'/>")
            wanted = request.headers.get("range")
            if wanted and wanted.startswith("bytes="):
                start, _, end = wanted[6:].partition("-")
                first, last = int(start), int(end) if end else len(AUDIO) - 1
                return httpx.Response(
                    206,
                    headers={
                        "content-type": "audio/mpeg",
                        "content-range": f"bytes {first}-{last}/{len(AUDIO)}",
                        "accept-ranges": "bytes",
                    },
                    content=streamed(AUDIO[first : last + 1]),
                )
            return httpx.Response(200, headers={"content-type": "audio/mpeg", "accept-ranges": "bytes"}, content=streamed(AUDIO))
        if request.url.path.endswith("/getCoverArt.view"):
            if query.get("id") == "al-1":
                return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=PICTURE)
            return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}")
        return httpx.Response(404)


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier):  # type: ignore[no-untyped-def]
    music = MusicServer()
    source = Source(tmp_path / "work")
    navidrome = NavidromeClient(
        "http://navidrome.test", "admin", "admin-password", client=httpx.Client(transport=httpx.MockTransport(music))
    )
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, youtube=source, navidrome=navidrome)) as client:  # type: ignore[arg-type]
        yield client, source, music


def kept_ref(client: TestClient) -> str:
    ref = str(resolve(client, "marwa", song())[0]["id"])
    with client.app.state.services.db.tx() as conn:  # type: ignore[attr-defined]
        refs.attach_file(conn, ref, navidrome_song_id="nd-42", path=None, codec="mp3", bitrate_kbps=192)
    return ref


def address(client: TestClient, ref: str, user: str = "marwa") -> str:
    response = client.get(f"{V1}/refs/{ref}/stream-url", params=creds(user))
    assert response.status_code == 200, response.text
    return str(response.json()["url"])


def test_a_kept_song_comes_from_the_music_server_as_the_servers_own_account(rig) -> None:  # type: ignore[no-untyped-def]
    client, source, music = rig
    url = address(client, kept_ref(client))

    response = client.get(url)

    assert response.status_code == 200 and response.content == AUDIO
    assert response.headers["content-type"] == "audio/mpeg" and response.headers["accept-ranges"] == "bytes"
    assert source.asked == [], "YouTube is not asked for a song the server keeps"
    asked = music.requests[-1].url.params
    assert asked["u"] == "admin" and asked["id"] == "nd-42"
    assert not {"p", "e", "sig"} & set(asked), "the person's signed address is not passed on"
    assert "marwa" not in str(music.requests[-1].url), "nothing of the person's login reaches the music server"


def test_range_is_passed_on_so_a_kept_song_can_be_jumped_in(rig) -> None:  # type: ignore[no-untyped-def]
    client, _source, _music = rig
    url = address(client, kept_ref(client))

    response = client.get(url, headers={"Range": "bytes=1000-1999"})

    assert response.status_code == 206 and response.content == AUDIO[1000:2000]
    assert response.headers["content-range"] == f"bytes 1000-1999/{len(AUDIO)}"


def test_the_quality_a_phone_asks_for_is_passed_on_and_checked(rig) -> None:  # type: ignore[no-untyped-def]
    client, _source, music = rig
    url = address(client, kept_ref(client))

    assert client.get(url + "&maxBitRate=128&format=mp3").status_code == 200
    asked = music.requests[-1].url.params
    assert asked["maxBitRate"] == "128" and asked["format"] == "mp3"

    assert client.get(url + "&maxBitRate=99999").status_code == 400
    assert client.get(url + "&format=exe").status_code == 400
    assert client.get(url + "&maxBitRate=0&format=raw").status_code == 200
    assert "maxBitRate" not in music.requests[-1].url.params and "format" not in music.requests[-1].url.params


def test_a_song_the_music_server_has_lost_is_played_from_youtube_instead(rig) -> None:  # type: ignore[no-untyped-def]
    client, source, music = rig
    music.has_song = False
    url = address(client, kept_ref(client))

    response = client.get(url)

    assert response.status_code == 200 and response.content == DATA
    assert len(source.asked) == 1


def test_an_address_that_was_changed_or_has_expired_is_refused(rig) -> None:  # type: ignore[no-untyped-def]
    client, _source, music = rig
    url = address(client, kept_ref(client))

    assert client.get(url.replace("sig=", "sig=0")).status_code == 401
    assert client.get(url.replace("&e=", "&e=1")).status_code == 401
    assert not any(r.url.path.endswith("/stream.view") for r in music.requests)


def test_a_cover_has_a_signed_address_and_comes_from_the_music_server(rig) -> None:  # type: ignore[no-untyped-def]
    client, _source, music = rig
    answer = client.get(f"{V1}/covers/al-1/url", params={**creds("marwa"), "size": 300})
    assert answer.status_code == 200, answer.text
    url = answer.json()["url"]

    response = client.get(url)

    assert response.status_code == 200 and response.content == PICTURE
    assert response.headers["content-type"] == "image/jpeg" and "max-age" in response.headers["cache-control"]
    asked = music.requests[-1].url.params
    assert asked["id"] == "al-1" and asked["size"] == "300" and asked["u"] == "admin"


def test_covers_are_refused_without_the_signature_and_for_ids_that_are_not_ids(rig) -> None:  # type: ignore[no-untyped-def]
    client, _source, _music = rig
    url = client.get(f"{V1}/covers/al-1/url", params=creds("marwa")).json()["url"]

    assert client.get(url.replace("sig=", "sig=0")).status_code == 401
    assert client.get("/encore/cover/al-1").status_code in (400, 401)
    assert client.get(f"{V1}/covers/../etc/url", params=creds("marwa")).status_code == 404
    assert client.get(f"{V1}/covers/al-1/url", params={**creds("marwa"), "size": 5}).status_code == 400
    assert client.get(client.get(f"{V1}/covers/al-9/url", params=creds("marwa")).json()["url"]).status_code == 404


def test_one_cover_pass_opens_any_picture_for_a_week_and_nothing_else(rig) -> None:  # type: ignore[no-untyped-def]
    client, _source, _music = rig
    answer = client.get(f"{V1}/covers/pass", params=creds("marwa"))
    assert answer.status_code == 200, answer.text
    body = answer.json()
    ticket = body["pass"]
    assert set(ticket) == {"p", "e", "sig"}
    week_s = 7 * 24 * 3600
    assert week_s - 60 <= int(ticket["e"]) - time.time() <= week_s + 60
    assert body["expiresAt"] == int(ticket["e"]) * 1000

    # The same pass opens every picture, at any size, with no further round trip to the server.
    for cover_id, size in (("al-1", 300), ("al-1", 64)):
        response = client.get(f"/encore/cover/{cover_id}", params={**ticket, "size": size})
        assert response.status_code == 200 and response.content == PICTURE

    # A pass is for pictures: it is not the address of a song, and a changed or an old one is refused.
    ref = kept_ref(client)
    assert client.get(f"/encore/stream/{ref}", params=ticket).status_code == 401
    assert client.get("/encore/cover/al-1", params={**ticket, "sig": "0" * 32}).status_code == 401
    assert client.get("/encore/cover/al-1", params={**ticket, "e": "1"}).status_code == 401
    assert client.get("/encore/cover/al-1", params={**ticket, "p": "someone-else"}).status_code == 401
    assert client.get("/encore/cover/al-1", params={"size": 300}).status_code in (400, 401)


def test_a_cover_pass_needs_a_signed_in_device(rig) -> None:  # type: ignore[no-untyped-def]
    client, _source, _music = rig

    assert client.get(f"{V1}/covers/pass").status_code == 401


def test_a_download_can_ask_for_the_length_of_a_transcoded_song(rig) -> None:  # type: ignore[no-untyped-def]
    client, _source, music = rig
    url = address(client, kept_ref(client))

    assert client.get(url + "&maxBitRate=128&format=mp3&estimateContentLength=true").status_code == 200
    assert music.requests[-1].url.params["estimateContentLength"] == "true"

    assert client.get(url).status_code == 200
    assert "estimateContentLength" not in music.requests[-1].url.params
    assert client.get(url + "&estimateContentLength=maybe").status_code == 400
