"""Keeping: the whole song fetched through the stream proxy (sources/youtube/stream.py `download`)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from encore_server.sources.youtube.errors import DownloadError
from encore_server.sources.youtube.stream import CHUNK, FIRST_CHUNK, StreamProxy
from tests.sources.test_stream import FakeYouTube, Request, info_file

DATA = bytes(range(256)) * (3 * CHUNK // 256 + 7)  # a bit over three chunks


class Rig:
    def __init__(self, tmp: Path, youtube: FakeYouTube, *, extract=None, found=None) -> None:  # type: ignore[no-untyped-def]
        self.extracted: list[str] = []
        self.slept: list[float] = []
        self.youtube = youtube
        make = extract or info_file(size=len(DATA))

        def recording(video_id: str, path: Path) -> None:
            self.extracted.append(video_id)
            make(video_id, path)

        self.proxy = StreamProxy(
            candidates=lambda request: found if found is not None else [("aaaaaaaaaaa", "t", 200)],
            extract=recording,
            work_dir=tmp / "work",
            opener=youtube,
            sleep=self.slept.append,
        )
        self.stem = tmp / "keep" / "song"


def test_the_whole_file_arrives_in_order_and_is_renamed_when_complete(tmp_path: Path) -> None:
    rig = Rig(tmp_path, FakeYouTube(DATA))

    path = rig.proxy.download(Request("A", "B"), rig.stem, max_bytes=10**9)

    assert path.name == "song.webm" and path.read_bytes() == DATA
    assert not path.with_name("song.webm.part").exists()
    assert rig.youtube.requests[0] == f"bytes=0-{FIRST_CHUNK - 1}"
    assert rig.youtube.requests[1] == f"bytes={FIRST_CHUNK}-{FIRST_CHUNK + CHUNK - 1}"


def test_the_address_a_play_just_asked_for_is_reused(tmp_path: Path) -> None:
    rig = Rig(tmp_path, FakeYouTube(DATA))
    rig.proxy.open(Request("A", "B"), "bytes=0-9")

    rig.proxy.download(Request("A", "B"), rig.stem, max_bytes=10**9)

    assert rig.extracted == ["aaaaaaaaaaa"]


def test_an_address_that_has_expired_is_asked_for_again_once(tmp_path: Path) -> None:
    youtube = FakeYouTube(DATA)
    rig = Rig(tmp_path, youtube)
    rig.proxy.open(Request("A", "B"), "bytes=0-9")
    youtube.only_generation = 2

    path = rig.proxy.download(Request("A", "B"), rig.stem, max_bytes=10**9)

    assert path.read_bytes() == DATA and rig.extracted.count("aaaaaaaaaaa") == 2


def test_a_fresh_address_that_answers_403_for_a_few_seconds_is_waited_for(tmp_path: Path) -> None:
    rig = Rig(tmp_path, FakeYouTube(DATA, refuse_first=3))

    path = rig.proxy.download(Request("A", "B"), rig.stem, max_bytes=10**9)

    assert path.read_bytes() == DATA and rig.slept[:3] == [0.5, 0.5, 0.75]


def test_a_song_bigger_than_the_limit_is_refused_before_a_byte_is_fetched(tmp_path: Path) -> None:
    rig = Rig(tmp_path, FakeYouTube(DATA))

    with pytest.raises(DownloadError) as caught:
        rig.proxy.download(Request("A", "B"), rig.stem, max_bytes=1000)

    assert caught.value.code == "too_big" and rig.youtube.requests == []


def test_a_song_of_unknown_size_that_grows_past_the_limit_is_stopped_and_leaves_nothing(tmp_path: Path) -> None:
    rig = Rig(tmp_path, FakeYouTube(DATA), extract=info_file(size=None))

    with pytest.raises(DownloadError) as caught:
        rig.proxy.download(Request("A", "B"), rig.stem, max_bytes=FIRST_CHUNK + 10)

    assert caught.value.code == "too_big"
    assert list((tmp_path / "keep").glob("song*")) == []


def test_a_stream_that_dies_half_way_leaves_nothing_and_says_so(tmp_path: Path) -> None:
    rig = Rig(tmp_path, FakeYouTube(DATA, expired_after=2))

    with pytest.raises(DownloadError) as caught:
        rig.proxy.download(Request("A", "B"), rig.stem, max_bytes=10**9)

    assert caught.value.code == "download_failed"
    assert list((tmp_path / "keep").glob("song*")) == []


def test_an_upload_that_is_gone_is_replaced_by_the_next_best(tmp_path: Path) -> None:
    ok = info_file(size=len(DATA))

    def extract(video_id: str, path: Path) -> None:
        if video_id == "aaaaaaaaaaa":
            raise DownloadError("unavailable")
        ok(video_id, path)

    rig = Rig(tmp_path, FakeYouTube(DATA), extract=extract, found=[("aaaaaaaaaaa", "t", 200), ("bbbbbbbbbbb", "t", 200)])

    assert rig.proxy.download(Request("A", "B"), rig.stem, max_bytes=10**9).read_bytes() == DATA


def test_nothing_found_is_not_found_and_a_block_is_passed_on(tmp_path: Path) -> None:
    nothing = Rig(tmp_path, FakeYouTube(DATA), found=[])
    with pytest.raises(DownloadError) as caught:
        nothing.proxy.download(Request("A", "B"), nothing.stem, max_bytes=10**9)
    assert caught.value.code == "not_found"

    def blocked(video_id: str, path: Path) -> None:
        raise DownloadError("blocked")

    busy = Rig(tmp_path, FakeYouTube(DATA), extract=blocked)
    with pytest.raises(DownloadError) as caught:
        busy.proxy.download(Request("A", "B"), busy.stem, max_bytes=10**9)
    assert caught.value.code == "blocked"


def test_a_refused_chunk_is_logged_with_where_it_happened_and_never_the_signed_address(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Audit B-104: 403 on a later chunk, also on the fresh address the retry asks for. The log says the byte and the host, not the address."""
    rig = Rig(tmp_path, FakeYouTube(DATA, expired_after=2))

    with caplog.at_level(logging.WARNING, logger="encore_server.sources.youtube.stream"), pytest.raises(DownloadError) as error:
        rig.proxy.download(Request("A", "B"), rig.stem, max_bytes=10**9)

    assert error.value.code == "download_failed"
    said = " | ".join(r.getMessage() for r in caplog.records)
    assert f"HTTP 403 from rr1.example.googlevideo.com at byte {FIRST_CHUNK + CHUNK}" in said
    assert "on a fresh address, giving up" in said
    assert "videoplayback" not in said and "g=" not in said, "the signed address is never logged"


def test_a_chunk_refused_in_the_middle_of_a_long_file_is_asked_for_again_where_it_was(tmp_path: Path) -> None:
    """Audit B-104 and B-93: about one chunk in eight is refused (403), and a 2-hour recording is about 80 chunks. The file used to be thrown away and fetched
    again from byte 0 once; now only the refused chunk is asked for again, so the file completes whatever the number of chunks."""
    youtube = FakeYouTube(DATA, refuse_nth=frozenset({3}))
    rig = Rig(tmp_path, youtube)

    path = rig.proxy.download(Request("A", "B"), rig.stem, max_bytes=10**9)

    assert path.read_bytes() == DATA
    asked = [r for r in youtube.requests]
    assert asked.count(asked[2]) == 2, "the refused chunk was asked for twice, the others once"
    assert asked[0] == f"bytes=0-{FIRST_CHUNK - 1}"
    assert rig.extracted == ["aaaaaaaaaaa"], "the same address was tried again first: no new look-up at YouTube"
    assert rig.slept == [1.0], "a short wait before the second try"
    assert not path.with_name(path.name + ".part").exists()


def test_a_chunk_that_keeps_being_refused_gives_up_after_a_few_tries_and_leaves_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    youtube = FakeYouTube(DATA, expired_after=2)  # the first two requests are fine, every later one is refused
    rig = Rig(tmp_path, youtube)

    with caplog.at_level(logging.WARNING), pytest.raises(DownloadError) as caught:
        rig.proxy.download(Request("A", "B"), rig.stem, max_bytes=10**9)

    assert caught.value.code == "download_failed"
    # each of the two rounds (the kept address, then a fresh one) makes the first two requests, then asks for the third chunk 1 + 3 times
    assert len(youtube.requests) <= 2 * (2 + 1 + 3) + 2
    assert not any(rig.stem.parent.glob("song*")), "no half file is left"


def test_the_keep_limits_hold_a_two_and_a_half_hour_recording() -> None:
    """Owner, 7 Nov 2026: songs up to 2 hours 30 may be saved (his 2-hour recitation could not be): 150 minutes and a size that holds it at 160 kbit/s."""
    from encore_server.keeper.keeper import KeepSettings

    settings = KeepSettings(music_dir=Path("/music"))
    assert settings.max_minutes == 150
    assert settings.max_file_mb * 1024 * 1024 >= 150 * 60 * 160_000 // 8
