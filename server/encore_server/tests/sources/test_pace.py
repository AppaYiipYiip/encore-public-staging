"""Background work takes turns at YouTube; a person's tap does not wait (2026-10-22: a home address was refused after about 35 look-ups in a burst)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from encore_server.sources.youtube.pace import Pacer
from encore_server.sources.youtube.source import Wanted, YoutubeSource


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def pacer(clock: Clock, mean_s: float = 8.0) -> Pacer:
    return Pacer(mean_s, clock=clock, sleep=clock.sleep, uniform=lambda low, high: (low + high) / 2)


def test_the_first_request_goes_at_once_and_each_next_one_waits_its_turn() -> None:
    clock = Clock()
    p = pacer(clock)

    waits = [p.wait_turn() for _ in range(4)]

    assert waits[0] == 0.0
    assert waits[1:] == [8.0, 8.0, 8.0], "one every eight seconds on average: nothing like a burst"
    assert clock.now == 1000.0 + 24.0


def test_a_quiet_spell_resets_the_wait() -> None:
    clock = Clock()
    p = pacer(clock)
    p.wait_turn()

    clock.now += 60.0

    assert p.wait_turn() == 0.0


def test_the_default_pace_is_four_seconds_and_the_host_picks_between_three_and_eight() -> None:
    """7 Nov 2026, the owner (D-67): "fix it at 3 s a song, let the admin pick between 3 and 8, default 4". 200 songs in about 10 minutes at 3, 13 at 4, 27 at 8."""
    from encore_server.config import Settings

    assert Settings.from_env({}).youtube_pace_s == 4.0
    assert Settings.from_env({"ENCORE_YOUTUBE_PACE_S": "3"}).youtube_pace_s == 3.0
    assert Settings.from_env({"ENCORE_YOUTUBE_PACE_S": "5.5"}).youtube_pace_s == 5.5
    assert Settings.from_env({"ENCORE_YOUTUBE_PACE_S": "8"}).youtube_pace_s == 8.0
    seen: list[tuple[float, float]] = []
    clock = Clock()

    def uniform(low: float, high: float) -> float:
        seen.append((low, high))
        return low

    Pacer(clock=clock, sleep=clock.sleep, uniform=uniform).wait_turn()  # no mean given: the class default

    assert seen == [(2.0, 6.0)]


def test_a_pace_outside_three_to_eight_is_held_to_the_nearest_end_and_a_typo_is_the_default() -> None:
    """A typo or a 0 in `.env` must not switch pacing off or make it crawl: the burst is what got the address refused."""
    from encore_server.config import Settings

    for written, expected in [
        ("0", 3.0),
        ("1", 3.0),
        ("-5", 3.0),
        ("20", 8.0),
        ("1e9", 8.0),
        ("", 4.0),
        ("fast", 4.0),
        ("nan", 4.0),
        (" 6 ", 6.0),
    ]:
        assert Settings.from_env({"ENCORE_YOUTUBE_PACE_S": written}).youtube_pace_s == expected, written


def test_the_compose_file_passes_the_pace_through_so_a_host_can_set_it_in_dot_env() -> None:
    compose = (Path(__file__).resolve().parents[2] / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    assert "ENCORE_YOUTUBE_PACE_S: ${ENCORE_YOUTUBE_PACE_S:-4}" in compose


def test_the_gaps_are_random_between_half_and_one_and_a_half_times_the_mean() -> None:
    clock = Clock()
    seen: list[tuple[float, float]] = []

    def uniform(low: float, high: float) -> float:
        seen.append((low, high))
        return low

    Pacer(10.0, clock=clock, sleep=clock.sleep, uniform=uniform).wait_turn()

    assert seen == [(5.0, 15.0)]


class FakeResolver:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def resolve_ranked(self, want: Any) -> list[Any]:
        self.asked.append(want.title)
        return []


class FakeProxy:
    def __init__(self) -> None:
        self.downloads: list[str] = []

    def download(self, wanted: Wanted, stem: Path, *, max_bytes: int) -> Path:
        self.downloads.append(wanted.title)
        return stem.with_suffix(".webm")


def wanted(title: str, video: str | None = None) -> Wanted:
    return Wanted(ref_id="sr_1", artist="A", title=title, album=None, duration_s=200, video_id=video)


def source(tmp_path: Path, clock: Clock) -> tuple[YoutubeSource, FakeResolver, FakeProxy]:
    resolver, proxy = FakeResolver(), FakeProxy()
    youtube = YoutubeSource(tmp_path, resolver=resolver, extractor=object(), proxy=proxy, pace=pacer(clock))  # type: ignore[arg-type]
    return youtube, resolver, proxy


def test_looking_up_and_keeping_share_one_queue_at_youtube(tmp_path: Path) -> None:
    clock = Clock()
    youtube, resolver, proxy = source(tmp_path, clock)

    youtube.find(wanted("One"))
    youtube.find(wanted("Two"))
    youtube.download(wanted("Two"), tmp_path / "x", max_bytes=1000)

    assert resolver.asked == ["One", "Two"] and proxy.downloads == ["Two"]
    assert clock.slept == [8.0, 8.0]


def test_a_song_whose_upload_is_known_needs_no_look_up_and_no_wait(tmp_path: Path) -> None:
    clock = Clock()
    youtube, resolver, _ = source(tmp_path, clock)

    youtube.find(wanted("Known", video="abcdefghijk"))
    youtube.find(wanted("Known", video="abcdefghijk"))

    assert resolver.asked == [] and clock.slept == []
