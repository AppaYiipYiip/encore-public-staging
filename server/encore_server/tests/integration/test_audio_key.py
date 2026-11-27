"""N-38, the proof on the real ffmpeg: the audio-only key (`audio_key.py`) does not move when the TAGS of a file are rewritten, and does move when the sound is not the same.

The unit tests (`tests/test_audio_key.py`) give the hash; what they cannot say is whether `ffmpeg -map 0:a:0 -c copy -f hash` really leaves tags, covers and containers out for each container the
music folder holds. That is the whole promise of the key (a repair that rewrites tags must not make a phone download the song again), so it is proved here, with the keeper's own tag writer
(`keeper.tagging.write_tags`, mutagen first and the ffmpeg remux when mutagen cannot) and with a plain ffmpeg remux, for Opus, FLAC, AAC in MP4 and MP3, with a cover added.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from encore_server import refs
from encore_server.audio_key import AudioKeys, Unreadable, audio_key_of
from encore_server.db import Database
from encore_server.keeper.tagging import Tags, ffmpeg_args, write_tags
from tests.integration.conftest import ffmpeg

pytestmark = pytest.mark.integration

CODECS = {".opus": "libopus", ".flac": "flac", ".m4a": "aac", ".mp3": "libmp3lame"}


def tone(path: Path, *, hertz: int = 440, seconds: int = 3, **tags: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = [arg for key, value in tags.items() for arg in ("-metadata", f"{key}={value}")]
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency={hertz}:duration={seconds}", "-c:a", CODECS[path.suffix], *meta, str(path))
    return path


def cover(path: Path) -> bytes:
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=200x200", "-frames:v", "1", str(path))
    return path.read_bytes()


TAGS = Tags(
    title="Weird Fishes",
    artist="Radiohead",
    artists=("Radiohead",),
    album="In Rainbows",
    album_artist="Radiohead",
    track=4,
    year=2007,
)


@pytest.mark.parametrize("suffix", sorted(CODECS))
def test_a_tag_rewrite_with_a_new_cover_does_not_change_the_key_whatever_the_container(tmp_path: Path, suffix: str) -> None:
    song = tone(tmp_path / f"song{suffix}", title="Old title", artist="Old artist")
    key = audio_key_of(song)
    assert key.startswith("a1:") and len(key) == 3 + 32
    size = song.stat().st_size

    # 1. the keeper's own writer, with a cover
    assert write_tags(song, TAGS, cover(tmp_path / "front.jpg")), "the keeper's tag writer wrote the file"
    if (
        suffix in (".opus", ".m4a")
    ):  # written in place by mutagen with a cover: certainly bigger (a FLAC's padding or a remux can leave the size alone, which proves nothing either way)
        assert song.stat().st_size != size, "the rewrite changed the file's size: the number the old key hashed"
    assert audio_key_of(song) == key, "and the key did not move"

    # 2. a plain ffmpeg remux that replaces every tag (what the fallback of the writer does, and what other tools do)
    remuxed = tmp_path / f"remuxed{suffix}"
    ffmpeg(
        *ffmpeg_args(song, remuxed, Tags(title="Another", artist="Somebody", artists=("Somebody",)))[4:]
    )  # [4:] drops "ffmpeg -y -loglevel error": the helper adds them
    assert audio_key_of(remuxed) == key, "a remux with other tags is the same sound"

    # 3. a byte-for-byte copy is the same key, of course
    copy = tmp_path / f"copy{suffix}"
    copy.write_bytes(song.read_bytes())
    assert audio_key_of(copy) == key


@pytest.mark.parametrize("suffix", sorted(CODECS))
def test_another_sound_is_another_key(tmp_path: Path, suffix: str) -> None:
    one = tone(tmp_path / f"one{suffix}", hertz=440)
    other_tone = tone(tmp_path / f"other{suffix}", hertz=660)
    longer = tone(tmp_path / f"longer{suffix}", hertz=440, seconds=4)
    keys = {audio_key_of(one), audio_key_of(other_tone), audio_key_of(longer)}
    assert len(keys) == 3, "a replaced or re-recorded file is not the same song file"


def test_a_re_encode_of_the_same_recording_is_another_key(tmp_path: Path) -> None:
    """A phone must fetch a better or different encode again: the key is of the stream, so re-encoding changes it."""
    source = tone(tmp_path / "source.flac")
    low, high = tmp_path / "low.opus", tmp_path / "high.opus"
    ffmpeg("-i", str(source), "-c:a", "libopus", "-b:a", "24k", str(low))
    ffmpeg("-i", str(source), "-c:a", "libopus", "-b:a", "96k", str(high))
    assert audio_key_of(low) != audio_key_of(high)


def test_a_file_that_is_not_audio_is_unreadable_not_keyed(tmp_path: Path) -> None:
    junk = tmp_path / "junk.opus"
    junk.write_bytes(b"this is not audio at all" * 40)
    with pytest.raises(Unreadable):
        audio_key_of(junk)


def test_the_hourly_errand_keys_a_library_on_the_real_ffmpeg_and_a_retag_makes_no_news(tmp_path: Path, db: Database) -> None:
    music = tmp_path / "music"
    song = tone(music / "Radiohead" / "In Rainbows" / "04 - Weird Fishes.opus", title="Weird Fishes", artist="Radiohead")
    with db.tx() as conn:
        ref = str(refs.resolve(conn, {"title": "Weird Fishes", "artists": ["Radiohead"]})["id"])
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path=song.relative_to(music).as_posix(),
            codec="opus",
            bitrate_kbps=64,
            meta={"size": song.stat().st_size},
        )

    first = AudioKeys(db, music).run_once()
    assert (first.made, first.unreadable, first.left) == (1, 0, 0)
    with db.read() as conn:
        served = refs.get_ref(conn, ref)["file"]["audioKey"]
        news = int(conn.execute("SELECT COUNT(*) FROM file_log").fetchone()[0])
    assert served == audio_key_of(song)

    # the server (or anybody) rewrites the tags; the music server's next scan reports the new size
    assert write_tags(song, TAGS, cover(tmp_path / "front.jpg"))
    with db.tx() as conn:
        conn.execute("UPDATE song_file SET meta = ?", (f'{{"size":{song.stat().st_size}}}',))
    again = AudioKeys(db, music).run_once()

    assert again.made == 0, "the file was hashed again (its size changed) and the key is the same one"
    with db.read() as conn:
        assert refs.get_ref(conn, ref)["file"]["audioKey"] == served
        assert int(conn.execute("SELECT COUNT(*) FROM file_log").fetchone()[0]) == news, (
            "no phone is told anything: nothing it holds changed"
        )
