"""Keeping: the whole song fetched through the stream proxy (sources/youtube/stream.py `download`)."""

from __future__ import annotations

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
