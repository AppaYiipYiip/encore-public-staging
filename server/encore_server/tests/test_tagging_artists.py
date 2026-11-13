"""Each artist of a song on its own: the `ARTISTS` tag (audit B-119).

Proved on the music server's own version (Navidrome 0.64.2, a throwaway container, 7 Nov 2026): a file tagged `ARTIST=Post Malone, Swae Lee` is linked to an
artist of that whole name (no album, outside the artist index the apps read); the same file with `ARTISTS` = [Post Malone, Swae Lee] is linked to the real
Post Malone and Swae Lee, and the shown artist string is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from encore_server.keeper import tagging
from encore_server.keeper.tagging import Tags


class FakeAudio(dict):  # type: ignore[type-arg]
    """What `mutagen.File` returns: a mapping of tag name to values, saved in place."""

    saved = False

    def save(self) -> None:
        self.saved = True


@pytest.fixture
def audio(monkeypatch: pytest.MonkeyPatch) -> FakeAudio:
    fake = FakeAudio()
    import mutagen

    monkeypatch.setattr(mutagen, "File", lambda path, easy=False: fake)
    return fake


def write(path: str, *artists: str, album_artist: str | None = None) -> bool:
    tags = Tags(
        title="Sunflower",
        artist=", ".join(artists),
        artists=tuple(artists),
        album="Album",
        album_artist=album_artist or artists[0],
    )
    return tagging._with_mutagen(Path(path), tags, None)


def test_opus_gets_each_artist_as_its_own_value_and_keeps_the_joined_string(audio: FakeAudio) -> None:
    assert write("/m/a.opus", "Post Malone", "Swae Lee")

    assert audio["artists"] == ["Post Malone", "Swae Lee"]
    assert audio["artist"] == ["Post Malone, Swae Lee"]
    assert audio["albumartist"] == ["Post Malone"]
    assert audio.saved


def test_five_artists_all_get_their_value_in_order(audio: FakeAudio) -> None:
    assert write("/m/a.opus", "Drake", "Kanye West", "Lil Wayne", "Eminem", "Travis Scott")

    assert audio["artists"] == ["Drake", "Kanye West", "Lil Wayne", "Eminem", "Travis Scott"]
    assert audio["albumartist"] == ["Drake"], "the album artist is the first artist, whoever sings with them"


def test_an_artist_with_a_comma_in_the_name_is_kept_whole(audio: FakeAudio) -> None:
    assert write("/m/a.opus", "Tyler, The Creator", "Kali Uchis")

    assert audio["artists"] == ["Tyler, The Creator", "Kali Uchis"]
    assert audio["artist"] == ["Tyler, The Creator, Kali Uchis"]


def test_a_song_by_one_artist_gets_no_artists_tag(audio: FakeAudio) -> None:
    assert write("/m/a.opus", "Radiohead")

    assert "artists" not in audio
    assert audio["artist"] == ["Radiohead"]


def test_an_m4a_gets_the_same_in_the_freeform_atom_picard_uses(audio: FakeAudio) -> None:
    assert write("/m/a.m4a", "Post Malone", "Swae Lee")

    assert audio["----:com.apple.iTunes:ARTISTS"] == [b"Post Malone", b"Swae Lee"]
    assert audio["\xa9ART"] == ["Post Malone, Swae Lee"]


def test_the_ffmpeg_fallback_cannot_write_it_and_says_so_in_the_arguments_it_builds() -> None:
    argv: list[Any] = tagging.ffmpeg_args(Path("in.opus"), Path("out.opus"), Tags(title="T", artist="A, B", artists=("A", "B")))

    assert "artists=A" not in " ".join(argv), "ffmpeg -metadata cannot write one tag twice: the fallback leaves it out"
    assert "artist=A, B" in " ".join(argv)
