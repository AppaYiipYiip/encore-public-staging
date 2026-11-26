"""N-44 (audit B-136): the plain match (an upload seen only by its title, its channel and its length) needs the TITLE too.

Before: `score_plain` gave 2.5 (the artist's own channel) + 2.0 (the artist) + 3.0 (the length to the second) = 7.5 with no evidence about the title at all, and `ACCEPT` is 4.0,
so ANOTHER song of the artist, uploaded on the artist's own channel at the same length, was accepted and kept under the right name: a permanent wrong identity. The
structured path (a YouTube Music "song" result) already had a title gate (`lean.rank`); the plain path had none. Two substring branches also bypassed the rule P2-25 added to
`textnorm.ratio` (a dense-script name of up to four characters is compared for EQUALITY).

**The corpus is real**: the titles, artists and lengths are what YouTube Music answered (`tests/fixtures/ytm`). The only thing a test adds is the STRESS the audit named: the
other song is given the wanted song's length (a different song of the same length is the case that goes wrong)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from encore_server.sources.youtube import lean
from encore_server.sources.youtube.lean import candidate_from_song, candidate_from_video
from encore_server.sources.youtube.scoring import Candidate, Want
from encore_server.textnorm import norm_title

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ytm"


def recorded_rows() -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(FIXTURES.glob("*.songs.json")) + sorted(FIXTURES.glob("*.videos.json")):
        kind = "video" if path.name.endswith(".videos.json") else "song"
        for raw in json.loads(path.read_text(encoding="utf-8"))["results"]:
            rows.append((kind, raw))
    return rows


def as_plain(kind: str, raw: dict[str, Any]) -> Candidate | None:
    """The upload as the PLAIN path sees it: its title, its channel and its length, and nothing the upload declares about itself."""
    candidate = candidate_from_video(raw) if kind == "video" else candidate_from_song(raw)
    if candidate is None:
        return None
    return Candidate(candidate.video_id, candidate.title, candidate.channel, candidate.duration_s, candidate.is_topic)


def real_uploads() -> list[Candidate]:
    seen: dict[str, Candidate] = {}
    for kind, raw in recorded_rows():
        candidate = as_plain(kind, raw)
        if candidate is not None and candidate.channel and candidate.duration_s:
            seen.setdefault(candidate.video_id, candidate)
    return list(seen.values())


def artist_of(upload: Candidate) -> str:
    """The artist a person asks for: the channel without the ` - Topic` YouTube adds to an artist's auto-generated channel."""
    return upload.channel.removesuffix(" - Topic")


def same_song_family(a: str, b: str) -> bool:
    """One title holds the other ("Weird Fishes" and "Weird Fishes / Arpeggi"): not a pair of two different songs."""
    one, two = norm_title(a), norm_title(b)
    return not one or not two or one in two or two in one


def wrong_song_pairs() -> list[tuple[Want, Candidate]]:
    """Every pair of two DIFFERENT songs of one artist among the real uploads, the other one on the artist's own channel at the wanted song's length."""
    uploads = real_uploads()
    pairs: list[tuple[Want, Candidate]] = []
    for wanted in uploads:
        for other in uploads:
            if (
                other.video_id == wanted.video_id
                or other.channel != wanted.channel
                or same_song_family(wanted.title, other.title)
            ):
                continue
            pairs.append(
                (Want(artist_of(wanted), wanted.title, None, wanted.duration_s), replace(other, duration_s=wanted.duration_s))
            )
    return pairs


#: Pairs of real titles that are NOT two different songs, so a plain upload of the one IS the other (the corpus cannot tell them apart by words; each is named here, with why):
#: one song spelled two ways by the catalogue (transliterated Arabic), and the same recitation in different uploads.
def _is_one_song_spelled_two_ways(a: str, b: str) -> bool:
    return {norm_title(a), norm_title(b)} in ({"kifak inta", "kifak enta"}, {"shtatellak", "ishtatillak"})


def _is_the_same_recitation(a: str, b: str) -> bool:
    needle = norm_title("البقرة")  # Al-Baqarah, as the fold writes it
    return needle in norm_title(a) and needle in norm_title(b)


#: **KNOWN LIMIT, pinned so that it is seen when it changes** (N-44 note): two titles that differ only in a part number written two ways ("Pt. II" and "Pt. 3", 0.94 alike once the
#: spaces are put aside) are one song to a title bar and two songs to a person ("N.Y. State of Mind, Pt. II" is not "NY State Of Mind Pt. 3"). Only the declared album or the length can tell them
#: apart, and the length is what this corpus gives away on purpose.
def _is_the_known_part_number_limit(a: str, b: str) -> bool:
    return "state of mind" in norm_title(a) and "state of mind" in norm_title(b)


def test_the_corpus_is_real_and_big_enough_to_mean_something() -> None:
    assert len(real_uploads()) >= 25
    assert len(wrong_song_pairs()) >= 25


def test_another_song_of_the_artist_at_the_same_length_is_never_taken() -> None:
    taken = [
        (want, candidate)
        for want, candidate in wrong_song_pairs()
        if lean.rank(want, [candidate])
        and not _is_one_song_spelled_two_ways(want.title, candidate.title)
        and not _is_the_same_recitation(want.title, candidate.title)
    ]
    unexplained = [
        f"want {want.artist} - {want.title} ({want.duration_s} s), taken {candidate.title!r} on {candidate.channel!r}"
        for want, candidate in taken
        if not _is_the_known_part_number_limit(want.title, candidate.title)
    ]
    assert not unexplained, f"{len(unexplained)} wrong songs taken, for example: {unexplained[:5]}"
    assert taken, "the known limit is pinned: if this fails the limit is gone, delete it and its helper"


def test_the_right_upload_is_still_taken_in_the_forms_uploads_come_in() -> None:
    lost: list[str] = []
    for upload in real_uploads():
        if not norm_title(upload.title) or "(" in artist_of(upload) or any(sep in upload.title for sep in (" - ", " | ")):
            continue  # a title that is only a bracketed phrase (see the test below), and a channel called `Phill (Italy)`, which is no artist name a person asks for
        want = Want(artist_of(upload), upload.title, None, upload.duration_s)
        forms = [
            upload,
            replace(upload, title=f"{artist_of(upload)} - {upload.title}"),
            replace(upload, title=f"{upload.title} - {artist_of(upload)}"),
            replace(upload, title=f"{artist_of(upload)} - {upload.title} (Official Video)"),
            replace(upload, title=f"{upload.title} (Official Audio)"),
        ]
        for form in forms:
            if not lean.rank(want, [form]):
                lost.append(f"want {want.title!r}, refused {form.title!r}")
    assert not lost, f"{len(lost)} right uploads refused, for example: {lost[:5]}"


def test_a_title_with_nothing_to_compare_is_not_taken_on_the_artist_and_the_length_alone() -> None:
    """THE COST, said by a test: a song whose whole title is a bracketed phrase (Radiohead's `(Nice Dream)`) folds to NOTHING (`norm_title` removes brackets with what they hold), so there is no
    title evidence and the plain path no longer takes it on the artist and the length alone (7.5 points before). The song path refused it already (`title_matches`). It is found as a SONG result
    or not at all, which is "not found" and not a wrong song. The proper fix is in the fold, which is permanent identity (`norm_key`): its own item, not this one."""
    want = Want("Radiohead", "(Nice Dream)", None, 233)
    assert norm_title(want.title) == ""
    assert lean.rank(want, [Candidate("nd1", "(Nice Dream)", "Radiohead", 233)]) == []


# The three runs the audit named (B-136): a Latin case and the two dense-script ones. The inputs are the audit's own; the answer expected is "not found".
def test_the_audit_run_creep_and_karma_police() -> None:
    want = Want("Radiohead", "Creep", None, 238)
    other = Candidate("karma1", "Karma Police", "Radiohead", 240)
    assert lean.rank(want, [other]) == []


def test_the_audit_run_a_short_han_title_is_not_a_substring_of_another_title() -> None:
    want = Want("King Gnu", "白日", None, None)
    other = Candidate("hakujitsu1", "白日の夢 - 別の歌手", "別の歌手", None)
    assert lean.rank(want, [other]) == []


def test_the_audit_run_a_short_han_artist_is_not_a_substring_of_a_channel_name() -> None:
    want = Want("嵐", "Happiness", None, 240)
    other = Candidate("different1", "Different Song", "嵐 Fan Channel", 240)
    assert lean.rank(want, [other]) == []


def test_a_longer_title_that_merely_holds_the_wanted_one_is_another_song() -> None:
    """The substring branch scored ANY upload whose title contained the wanted one at 0.9 (4.5 points: over the bar by itself): `Hurt` in `Hurt Me`. A constructed probe of the rule (the real
    corpus above holds no such pair)."""
    want = Want("Johnny Cash", "Hurt", None, 216)
    assert lean.rank(want, [Candidate("hurtme1", "Hurt Me", "Johnny Cash", 216)]) == []
    assert lean.rank(want, [Candidate("hurt1", "Johnny Cash - Hurt (Official Music Video)", "Johnny Cash", 216)])


def test_a_short_dense_script_artist_is_not_found_inside_another_name() -> None:
    """The artist evidence of the plain path: `嵐` in `嵐山 Channel` (a place that merely holds the character) was worth 2.0 points. A short dense-script name is found only as a whole
    word (B-136 (b)): the title `嵐 - Happiness` has it, the channel `嵐山` does not."""
    from encore_server.sources.youtube.scoring import score_plain

    inside = score_plain(Want("嵐", "Happiness", None, 240), Candidate("place1", "Happiness", "嵐山 Channel", 240))
    assert "artist" not in inside.reasons and "artist channel" not in inside.reasons, inside.reasons
    whole = score_plain(Want("嵐", "Happiness", None, 240), Candidate("own1", "嵐 - Happiness", "嵐", 240))
    assert "artist" in whole.reasons


def real_video(fixture: str, title_has: str) -> Candidate:
    """A REAL video result (`tests/fixtures/ytm/<fixture>.videos.json`) as the plain path sees it."""
    for raw in json.loads((FIXTURES / f"{fixture}.videos.json").read_text(encoding="utf-8"))["results"]:
        if title_has in raw["title"]:
            candidate = as_plain("video", raw)
            assert candidate is not None
            return candidate
    raise AssertionError(f"no recorded video with {title_has!r} in {fixture}")


def test_a_title_in_two_scripts_on_the_artists_own_channel_is_taken() -> None:
    """THE RECALL CASE the advisor named (26 Nov 2026), on real answers: Arabic artists' own channels write `Latin title | Arabic title` as a matter of course
    (Wael Kfoury's `Wael Kfoury - Layel W Raad | وائل كفوري - ليل و رعد`). Before N-44 such an upload was taken on the artist and the length; the word-by-word bar alone would refuse
    it, which for an Arabic library is a song never found."""
    upload = real_video("ya-rab-wael-kfoury", "Layel W Raad")
    assert upload.channel == "Wael Kfoury" and "|" in upload.title
    want = Want("Wael Kfoury", "Layel W Raad", None, upload.duration_s)
    assert lean.rank(want, [upload])


def test_a_title_in_two_scripts_needs_the_length_to_the_second() -> None:
    """The twice-written title is taken on the artist's own channel AND the wanted length to the second: ten seconds off is another cut (a live take, an extended one)."""
    upload = real_video("ya-rab-wael-kfoury", "Layel W Raad")
    want = Want("Wael Kfoury", "Layel W Raad", None, (upload.duration_s or 0) + 10)
    assert lean.rank(want, [upload]) == []


def test_latin_letters_the_fold_leaves_alone_are_not_another_script() -> None:
    """Found by the advisor's read of #141: `norm_title` maps `\u00fc \u0131 \u00f8 \u0142` to ASCII but leaves `\u025b \u0254 \u014b \u0253` (the letters of Ghanaian and Congolese titles) as they are: they are
    not ASCII, and a test by ASCII called them "another script". Another SONG of the artist's own channel at the same length, whose title holds the wanted one and then words in those
    letters, was taken as the title written twice. The script is read by the letter's Unicode name (`textnorm.non_latin`)."""
    want = Want("Sarkodie", "Mama", None, 215)
    other = Candidate("mama2", "Mama \u025bk\u0254", "Sarkodie", 215)
    assert norm_title(other.title).isascii() is False
    assert lean.rank(want, [other]) == []
    assert lean.rank(want, [Candidate("mama3", "Mama | \u0645\u0627\u0645\u0627", "Sarkodie", 215)])


def test_another_song_in_two_scripts_on_the_same_channel_is_not_taken() -> None:
    upload = real_video("ya-rab-wael-kfoury", "Safha We Tawaita")
    want = Want("Wael Kfoury", "Layel W Raad", None, upload.duration_s)  # the length is given away on purpose
    assert lean.rank(want, [upload]) == []


def test_a_title_in_two_scripts_on_a_fans_channel_is_not_taken_on_the_rendering_alone() -> None:
    """The same form on somebody else's channel (a fan, a cover, an AI version) is no evidence of the artist's own recording: the old rule gave it 3.0, under the bar, and so does this one."""
    upload = real_video("kifak-inta-fairuz", "Kifak Enta | ")
    assert upload.channel != "Fairouz"
    want = Want("Fairouz", "Kifak Enta", None, upload.duration_s)
    assert lean.rank(want, [upload]) == []


@pytest.mark.parametrize(
    ("title", "channel"),
    [
        ("Creep", "Radiohead"),
        ("Radiohead - Creep", "Radiohead"),
        ("Creep - Radiohead", "Radiohead - Topic"),
        ("Radiohead - Creep (Official Video)", "Radiohead"),
        ("CREEP", "Radiohead"),
    ],
)
def test_the_right_upload_of_the_audit_song_is_taken(title: str, channel: str) -> None:
    want = Want("Radiohead", "Creep", None, 238)
    assert lean.rank(want, [Candidate("creep1", title, channel, 238, is_topic=channel.endswith("Topic"))])


def test_a_short_han_title_is_taken_when_the_upload_is_that_title() -> None:
    want = Want("King Gnu", "白日", None, 200)
    assert lean.rank(want, [Candidate("hakujitsu2", "King Gnu - 白日 (Official Video)", "King Gnu", 200)])
