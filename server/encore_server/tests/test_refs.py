from __future__ import annotations

import pytest

from encore_server import refs
from encore_server.db import Database
from encore_server.errors import ApiError
from encore_server.textnorm import is_unknown_artist


def resolve(db: Database, **song: object) -> dict[str, object]:
    base = {"title": "Weird Fishes / Arpeggi", "artists": ["Radiohead"], "durationMs": 318000}
    with db.tx() as conn:
        return refs.resolve(conn, {**base, **song})


def test_the_same_song_described_twice_is_one_ref(db: Database) -> None:
    assert resolve(db)["id"] == resolve(db)["id"]


def test_a_description_that_differs_only_in_spelling_finds_the_same_ref(db: Database) -> None:
    first = resolve(db, title="Weird Fishes / Arpeggi", artists=["Radiohead"])
    again = resolve(db, title="weird fishes / arpeggi", artists=["RADIOHEAD"], durationMs=319500)
    assert again["id"] == first["id"], "a different case and a length within 3 seconds"


def test_a_different_length_is_a_different_recording(db: Database) -> None:
    studio = resolve(db, durationMs=318000)
    live = resolve(db, durationMs=345000)
    assert live["id"] != studio["id"]


def test_a_rework_is_not_the_plain_song(db: Database) -> None:
    plain = resolve(db, title="Fade Into You", artists=["Mazzy Star"], durationMs=295000)
    rework = resolve(db, title="Fade Into You (The Avener Rework)", artists=["Mazzy Star"], durationMs=295000)
    again = resolve(db, title="Fade Into You (2013 Remaster)", artists=["Mazzy Star"], durationMs=295000)
    assert rework["id"] != plain["id"]
    assert again["id"] == plain["id"], "a remaster mark is not a different song"


def test_the_isrc_wins_over_everything_else(db: Database) -> None:
    first = resolve(db, isrc="GBAYE0701234")
    other_title = resolve(db, title="Weird Fishes (single edit)", isrc="gb-aye-07-01234", durationMs=250000)
    assert other_title["id"] == first["id"]


def test_ids_from_the_catalogue_and_youtube_find_the_ref(db: Database) -> None:
    first = resolve(db, deezerId="12345", videoId="bgsmr7t8zGE")
    assert resolve(db, title="Something else entirely", artists=["Anybody"], deezerId="12345")["id"] == first["id"]
    assert resolve(db, title="Another", artists=["Other"], videoId="bgsmr7t8zGE")["id"] == first["id"]


PLACEHOLDERS = ["Unknown Artist", "unknown artist", "[Unknown Artist]", "UNKNOWN ARTIST "]


@pytest.mark.parametrize(
    ("name", "is_nobody"),
    [
        ("Unknown Artist", True),
        ("unknown artist", True),
        ("[Unknown Artist]", True),
        ("  UNKNOWN   ARTIST ", True),
        ("Unknown Mortal Orchestra", False),  # a real band
        ("Unknown", False),
        ("Unknown Artists", False),
        ("", False),
        ("Some Band", False),
    ],
)
def test_only_the_placeholder_itself_says_nobody(name: str, is_nobody: bool) -> None:
    assert is_unknown_artist(name) is is_nobody


@pytest.mark.parametrize("placeholder", PLACEHOLDERS)
def test_a_song_whose_only_artist_is_the_placeholder_is_never_found_by_its_name(db: Database, placeholder: str) -> None:
    """N-26: "Unknown Artist" names nobody, so artist + title + length says nothing about WHICH song this is. Two different videos with the same title
    and lengths a second apart are two refs, each keeping its own video (before: the second landed on the first ref and played the first song's audio)."""
    first = resolve(db, title="Intro", artists=[placeholder], durationMs=100_000, videoId="aaaaaaaaaaa")
    second = resolve(db, title="Intro", artists=[placeholder], durationMs=101_000, videoId="bbbbbbbbbbb")

    assert second["id"] != first["id"]
    assert (first["videoId"], second["videoId"]) == ("aaaaaaaaaaa", "bbbbbbbbbbb")


@pytest.mark.parametrize("placeholder", PLACEHOLDERS)
def test_the_placeholder_is_still_found_by_its_ids_so_the_same_import_twice_is_one_ref(db: Database, placeholder: str) -> None:
    first = resolve(db, title="Intro", artists=["Unknown Artist"], durationMs=100_000, videoId="aaaaaaaaaaa", isrc="GBAAA0000009")
    again = resolve(db, title="Intro", artists=[placeholder], durationMs=100_000, videoId="aaaaaaaaaaa")
    by_isrc = resolve(db, title="Another name", artists=[placeholder], durationMs=250_000, isrc="gb-aaa-00-00009")

    assert again["id"] == first["id"], "the video id finds it"
    assert by_isrc["id"] == first["id"], "the ISRC finds it"


def test_a_description_with_the_placeholder_and_no_id_at_all_is_a_new_ref_each_time_and_the_cost_is_written_down(
    db: Database,
) -> None:
    """DECISION (N-26): the placeholder carries no identity, and that includes a real artist literally named "Unknown Artist": a name that cannot be told
    from "nobody" cannot identify a song. The cost: a description with the placeholder and NO id (nothing in the server makes one repeatedly: an import
    always has the video, and the library scan finds a file's ref by the file first) is not found again. Its removal trigger: a source that describes
    such songs without ids twice gets ids, or the song's own file is matched first, as the scanner does."""
    one = resolve(db, title="Intro", artists=["Unknown Artist"], durationMs=100_000)
    two = resolve(db, title="Intro", artists=["Unknown Artist"], durationMs=100_000)

    assert one["id"] != two["id"]


def test_a_real_artist_is_still_found_by_name_and_so_is_one_that_only_has_the_placeholder_as_a_second_name(db: Database) -> None:
    first = resolve(db, title="Intro", artists=["Some Band"], durationMs=100_000)
    assert resolve(db, title="Intro", artists=["Some Band", "Unknown Artist"], durationMs=101_000)["id"] == first["id"]
    assert resolve(db, title="Intro", artists=["some band"], durationMs=99_000)["id"] == first["id"]


def test_a_merged_away_song_with_the_placeholder_is_not_a_door_to_another_song_by_name(db: Database) -> None:
    """The tombstone of a merged ref (N-11) also answers by artist + title + length. A tombstone made of the placeholder must not send a different
    nameless song to the survivor."""
    survivor = resolve(db, title="Other Song", artists=["Real Band"], durationMs=100_000)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO ref_merge (old_id, into_id, at, norm_key, duration_ms) VALUES (?,?,?,?,?)",
            ("sr_00000000000000000000000099", survivor["id"], 1, refs.norm_key("Unknown Artist", "Intro"), 100_000),
        )

    nameless = resolve(db, title="Intro", artists=["Unknown Artist"], durationMs=100_000, videoId="aaaaaaaaaaa")

    assert nameless["id"] != survivor["id"]


def facts_of(db: Database, ref_id: object) -> tuple[object, object]:
    with db.read() as conn:
        row = conn.execute("SELECT artist_basis, uploader FROM song_ref WHERE id = ?", (ref_id,)).fetchone()
    return row["artist_basis"], row["uploader"]


def resolve_as(db: Database, basis: str | None, uploader: str | None = None, **song: object) -> dict[str, object]:
    """What the importer does: the song AND how its artist was decided (keyword arguments of `refs.resolve`, never part of the description)."""
    base = {"title": "Windowpane", "artists": ["Opeth"], "durationMs": 478_000}
    with db.tx() as conn:
        return refs.resolve(conn, {**base, **song}, artist_basis=basis, uploader=uploader)


def stored(db: Database, ref_id: object) -> tuple[object, ...]:
    with db.read() as conn:
        row = conn.execute("SELECT title, artists, norm_key FROM song_ref WHERE id = ?", (ref_id,)).fetchone()
    return tuple(row)


def test_a_new_ref_keeps_how_its_artist_was_decided_and_who_uploaded_the_video(db: Database) -> None:
    ref = resolve_as(db, "title", "KEXP", title="Heartbeat (Live on KEXP)", artists=["Nneka"], videoId="IY2WwzI_86k")

    assert facts_of(db, ref["id"]) == ("title", "KEXP")


def test_a_ref_made_without_facts_has_none_and_none_means_as_before(db: Database) -> None:
    """A description of a phone, a library file or a ref from before N-26: NULL. Never `channel`: it is treated as a performer, as it always was."""
    assert facts_of(db, resolve(db)["id"]) == (None, None)


def test_the_uploader_is_a_fact_about_a_video_and_is_kept_only_with_one(db: Database) -> None:
    ref = resolve_as(
        db, "channel", "Some Channel", title="Heartbeat", artists=["Some Channel"]
    )  # no video: nothing to say who uploaded

    assert facts_of(db, ref["id"]) == ("channel", None)


def test_a_client_cannot_mark_itself_the_facts_are_never_read_from_a_description(db: Database) -> None:
    ref = resolve(
        db,
        title="Intro",
        artists=["Somebody"],
        videoId="aaaaaaaaaaa",
        artistBasis="declared",
        artist_basis="declared",
        uploader="Not Me",
    )

    assert facts_of(db, ref["id"]) == (None, None)


def test_the_facts_are_not_part_of_what_a_phone_is_told(db: Database) -> None:
    ref = resolve_as(db, "channel", "KEXP", title="Heartbeat", artists=["KEXP"], videoId="IY2WwzI_86k")

    with db.read() as conn:
        told = refs.get_ref(conn, str(ref["id"]))
    assert not [key for key in (*ref, *told) if "basis" in key.lower() or "uploader" in key.lower()]


def test_a_basis_nobody_knows_is_refused_where_it_is_given(db: Database) -> None:
    """A mistake of the importer, never of a person: it must not be stored and found later."""
    with pytest.raises(ValueError, match="artist basis"):
        resolve_as(db, "performer")


@pytest.mark.parametrize("basis", ["declared", "title"])
def test_a_performers_basis_fills_an_empty_one_when_the_artist_agrees(db: Database, basis: str) -> None:
    first = resolve(db, title="Windowpane", artists=["Opeth"], durationMs=478_000)  # from a phone or an old import: NULL
    again = resolve_as(db, basis, "Opeth", videoId="bgsmr7t8zGE", durationMs=478_500)

    assert again["id"] == first["id"]
    assert facts_of(db, first["id"]) == (basis, "Opeth"), "the ref took the video this reading came from, and who uploaded it"


@pytest.mark.parametrize("basis", ["channel", "unknown"])
def test_a_weaker_basis_never_fills_an_empty_one_of_a_ref_that_is_not_the_upload_it_read(db: Database, basis: str) -> None:
    """DECISION: a real performer's catalogue ref (NULL = performer) that is found by NAME for a UGC upload on the band's own channel must not be
    downgraded to `channel` (the finders would then never look for its picture or its cover). `channel` and `unknown` say something about THAT upload."""
    first = resolve_as(db, None, None, videoId="bgsmr7t8zGE")  # the ref already plays from another video
    again = resolve_as(db, basis, "Opeth", videoId="otherVideo1", durationMs=478_500)

    assert again["id"] == first["id"]
    assert facts_of(db, first["id"]) == (None, None)


@pytest.mark.parametrize("basis", ["channel", "unknown"])
def test_a_weaker_basis_fills_an_empty_one_when_it_is_the_same_video(db: Database, basis: str) -> None:
    first = resolve_as(
        db, None, None, videoId="bgsmr7t8zGE"
    )  # a ref from before N-26 (or a phone's) that plays from this very video
    again = resolve_as(db, basis, "Opeth", videoId="bgsmr7t8zGE")

    assert again["id"] == first["id"]
    assert facts_of(db, first["id"]) == (basis, "Opeth")


def test_the_basis_follows_the_artist_a_reading_of_another_artist_fills_no_basis_but_the_uploader_is_kept(db: Database) -> None:
    """The ref keeps the artist it has (slice 5 repairs a stored artist, deliberately not this): a basis is a fact about THAT artist string, so a reading
    that names somebody else says nothing about it. The uploader is a fact about the VIDEO, and it is exactly what the repair of slice 5 needs to
    recognise a ref filed under its channel."""
    first = resolve_as(db, None, None, title="Heartbeat (Live on KEXP)", artists=["KEXP"], videoId="IY2WwzI_86k")
    again = resolve_as(db, "title", "KEXP", title="Heartbeat (Live on KEXP)", artists=["Nneka"], videoId="IY2WwzI_86k")

    assert again["id"] == first["id"]
    assert facts_of(db, first["id"]) == (None, "KEXP"), (
        "no basis (it says something about Nneka, the ref's artist is KEXP) but the uploader: a fact about the video"
    )
    assert stored(db, first["id"])[:2] == ("Heartbeat (Live on KEXP)", '["KEXP"]')


@pytest.mark.parametrize("later", ["declared", "title", "channel", "unknown"])
def test_a_later_reading_never_changes_a_basis_that_is_set_nor_the_artist_title_or_key(db: Database, later: str) -> None:
    """The design (section 4) fills an EMPTY basis only. A stronger reading of the same song later (a Topic upload after a personal one, a re-import)
    changes nothing: upgrading `channel` to `declared` belongs to the repair of stored rows (slice 5) and to N-28 (the catalogue names the artist),
    which also rewrite the artist, title and key the facts describe."""
    first = resolve_as(db, "channel", "KEXP", title="Intro", artists=["Some Channel"], videoId="aaaaaaaaaaa", durationMs=100_000)
    kept_as_was = stored(db, first["id"])

    again = resolve_as(db, later, "Other", title="Intro", artists=["Some Channel"], videoId="aaaaaaaaaaa", durationMs=100_000)

    assert again["id"] == first["id"]
    assert facts_of(db, first["id"]) == ("channel", "KEXP")
    assert stored(db, first["id"]) == kept_as_was


def test_a_set_basis_is_not_weakened_either(db: Database) -> None:
    first = resolve_as(db, "declared", None, title="Windowpane", artists=["Opeth"])
    resolve_as(db, "channel", "Opeth", videoId="bgsmr7t8zGE", durationMs=478_100)

    assert facts_of(db, first["id"])[0] == "declared"


def test_the_uploader_of_a_ref_is_never_replaced(db: Database) -> None:
    first = resolve_as(db, "title", "KEXP", title="Nneka - Heartbeat", artists=["Nneka"], videoId="IY2WwzI_86k")
    resolve_as(db, "title", "Somebody Else", title="Nneka - Heartbeat", artists=["Nneka"], videoId="IY2WwzI_86k")

    assert facts_of(db, first["id"]) == ("title", "KEXP")


def test_what_a_ref_lacked_is_filled_in_by_a_later_description(db: Database) -> None:
    first = resolve(db)
    assert first["isrc"] is None and first["videoId"] is None
    richer = resolve(db, isrc="GBAYE0701234", videoId="bgsmr7t8zGE", coverUrl="https://e-cdns-images.dzcdn.net/c.jpg")
    assert richer["id"] == first["id"]
    assert (richer["isrc"], richer["videoId"], richer["coverUrl"]) == (
        "GBAYE0701234",
        "bgsmr7t8zGE",
        "https://e-cdns-images.dzcdn.net/c.jpg",
    )


def test_an_id_another_ref_owns_is_never_taken_from_it(db: Database) -> None:
    a = resolve(db, title="Song A", artists=["X"], videoId="aaaaaaaaaaa", durationMs=200000)
    b = resolve(db, title="Song B", artists=["Y"], durationMs=200000)
    again = resolve(db, title="Song B", artists=["Y"], videoId="aaaaaaaaaaa", durationMs=200000)
    assert again["id"] == a["id"], "the video id is matched first"
    assert b["id"] != a["id"]


def test_no_two_refs_share_an_isrc_even_in_a_race(db: Database) -> None:
    with db.tx() as conn:
        first = refs.resolve(conn, {"title": "A", "artists": ["X"], "isrc": "USRC17607839", "durationMs": 100000})
        # a second description with the same isrc but nothing else alike: matched by isrc, not made new
        second = refs.resolve(
            conn, {"title": "Totally different", "artists": ["Z"], "isrc": "USRC17607839", "durationMs": 999000}
        )
    assert second["id"] == first["id"]


@pytest.mark.parametrize(
    "bad", [None, "text", {}, {"title": "x"}, {"artists": ["a"]}, {"title": "", "artists": ["a"]}, {"title": "t", "artists": []}]
)
def test_what_cannot_be_a_song_is_refused_in_words(db: Database, bad: object) -> None:
    with pytest.raises(ApiError) as caught, db.tx() as conn:
        refs.resolve(conn, bad)
    assert caught.value.code == "validation" and "title and an artist" in caught.value.message


def test_odd_values_are_dropped_not_stored(db: Database) -> None:
    ref = resolve(
        db,
        title="  Spaced   out  ",
        artists=["  A  ", "", 5],
        trackNo="3",
        year=1800,
        durationMs=5,
        coverUrl="http://insecure/x.jpg",
        videoId="short",
    )
    assert ref["title"] == "Spaced out"
    assert ref["artists"] == ["A"]
    assert (ref["trackNo"], ref["year"], ref["durationMs"], ref["coverUrl"], ref["videoId"]) == (None, None, None, None, None)


def test_a_file_attached_to_a_ref_changes_nothing_about_the_ref(db: Database) -> None:
    ref = resolve(db)
    assert ref["file"] is None
    with db.tx() as conn:
        refs.attach_file(
            conn,
            str(ref["id"]),
            navidrome_song_id="nd-1",
            path="Encore/Radiohead/In Rainbows/05 - Weird Fishes.opus",
            codec="opus",
            bitrate_kbps=140,
        )
        again = refs.get_ref(conn, str(ref["id"]))
    assert again["id"] == ref["id"]
    assert again["file"]["navidromeSongId"] == "nd-1"


def test_replacing_the_file_moves_the_pointer_only(db: Database) -> None:
    ref = resolve(db)
    with db.tx() as conn:
        refs.attach_file(conn, str(ref["id"]), navidrome_song_id="nd-1", path="a.opus", codec="opus", bitrate_kbps=128)
        refs.attach_file(
            conn, str(ref["id"]), navidrome_song_id="nd-2", path="b.flac", codec="flac", bitrate_kbps=900, source="quality"
        )
        current = refs.get_ref(conn, str(ref["id"]))
        files = conn.execute("SELECT preferred FROM song_file WHERE ref = ? ORDER BY added_at", (ref["id"],)).fetchall()
    assert current["file"]["navidromeSongId"] == "nd-2", "the better file is the one used"
    assert [r["preferred"] for r in files] == [0, 1]
    assert current["id"] == ref["id"]


def test_attaching_the_same_file_twice_is_one_file(db: Database) -> None:
    ref = resolve(db)
    with db.tx() as conn:
        first = refs.attach_file(conn, str(ref["id"]), navidrome_song_id="nd-1", path="a.opus", codec="opus", bitrate_kbps=128)
        second = refs.attach_file(conn, str(ref["id"]), navidrome_song_id="nd-1", path="a.opus", codec="opus", bitrate_kbps=130)
        assert conn.execute("SELECT COUNT(*) FROM song_file").fetchone()[0] == 1
    assert first == second


def test_the_holder_of_a_file_is_found_by_id_for_many_ids_and_the_oldest_row_wins(db: Database) -> None:
    ids = [f"nd-{n}" for n in range(1050)]  # more than one query asks about at once
    with db.tx() as conn:
        first = refs.resolve(conn, {"title": "One", "artists": ["A"], "durationMs": 200000})["id"]
        second = refs.resolve(conn, {"title": "Two", "artists": ["B"], "durationMs": 200000})["id"]
        for n in (0, 400, 1049):  # at both ends of the chunks
            refs.attach_file(conn, first, navidrome_song_id=ids[n], path=None, codec="opus", bitrate_kbps=None, source="youtube")
        refs.attach_file(
            conn, second, navidrome_song_id=ids[400], path=None, codec="opus", bitrate_kbps=None, source="library"
        )  # held twice

    with db.read() as conn:
        holders = refs.file_holders(conn, [*ids, "", "nd-unknown"])

    assert sorted(holders) == sorted(ids[n] for n in (0, 400, 1049))
    assert {holders[i]["ref"] for i in holders} == {first}  # the first holder, not the later one


def test_a_file_for_an_unknown_ref_is_not_found(db: Database) -> None:
    with pytest.raises(ApiError) as caught, db.tx() as conn:
        refs.attach_file(conn, "sr_00000000000000000000000000", navidrome_song_id="x", path=None, codec=None, bitrate_kbps=None)
    assert caught.value.code == "not_found"


def test_a_play_that_found_the_upload_leaves_it_on_the_ref(db: Database) -> None:
    ref = resolve(db)
    with db.tx() as conn:
        assert refs.remember_video(conn, str(ref["id"]), "bgsmr7t8zGE") is True
        assert refs.remember_video(conn, str(ref["id"]), "zzzzzzzzzzz") is False, "the first one found is kept"
        assert refs.get_ref(conn, str(ref["id"]))["videoId"] == "bgsmr7t8zGE"


def test_an_upload_another_ref_owns_is_not_taken(db: Database) -> None:
    a = resolve(db, title="A", artists=["X"], videoId="aaaaaaaaaaa", durationMs=100000)
    b = resolve(db, title="B", artists=["Y"], durationMs=100000)
    with db.tx() as conn:
        assert refs.remember_video(conn, str(b["id"]), "aaaaaaaaaaa") is False
        assert refs.get_ref(conn, str(a["id"]))["videoId"] == "aaaaaaaaaaa"


def test_a_picture_address_is_kept_only_from_the_hosts_the_server_itself_would_fetch_from(db: Database) -> None:
    """B6 (QA-BACKEND): any https address a phone named as a song's picture was stored and then loaded by EVERY phone that shows the song: a
    member could make every other phone ask a host of their choosing (showing each phone's address to it). The keeper's own allow-list of picture
    hosts, which it already applies to what it fetches, applies here too."""
    for bad in (
        "https://evil.example/pixel.gif",
        "https://dzcdn.net.evil.example/x.jpg",
        "https://notdzcdn.net/x.jpg",
        "http://e-cdns-images.dzcdn.net/x.jpg",
        "https://user@evil.example/x.jpg",
        "javascript:alert(1)",
    ):
        assert resolve(db, title=f"Song for {bad}", coverUrl=bad)["coverUrl"] is None, bad

    for good in (
        "https://e-cdns-images.dzcdn.net/images/cover/abc/500x500.jpg",
        "https://i.ytimg.com/vi/abc/hqdefault.jpg",
        "https://lh3.googleusercontent.com/abc=w544",
        "https://coverartarchive.org/release/1/front",
        "https://i.scdn.co/image/abc",
    ):
        assert resolve(db, title=f"Song for {good}", coverUrl=good)["coverUrl"] == good, good


THUMB = "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg"
COVER = "https://cdn-images.dzcdn.net/images/cover/abc/1000x1000-000000-80-0-0.jpg"


def test_a_thumbnail_is_the_cover_of_a_song_that_has_none(db: Database) -> None:
    ref = resolve(db, thumbnailUrl=THUMB)
    assert ref["coverUrl"] == THUMB, "the app shows a ref's coverUrl: an imported song is not a letter tile (P1-26)"


def test_a_real_cover_beats_the_thumbnail_and_the_thumbnail_never_replaces_it(db: Database) -> None:
    made = resolve(db, coverUrl=COVER, thumbnailUrl=THUMB)
    assert made["coverUrl"] == COVER
    # the cover finder later finds a better picture for a song that had only a thumbnail
    other = resolve(db, title="Another", thumbnailUrl=THUMB)
    with db.tx() as conn:
        conn.execute("UPDATE song_ref SET cover_url = ? WHERE id = ?", (COVER, other["id"]))
    with db.read() as conn:
        assert refs.get_ref(conn, str(other["id"]))["coverUrl"] == COVER


def test_a_thumbnail_that_arrives_later_fills_a_song_that_has_no_picture(db: Database) -> None:
    assert resolve(db)["coverUrl"] is None
    assert resolve(db, thumbnailUrl=THUMB)["coverUrl"] == THUMB


def test_a_thumbnail_on_a_host_the_picture_rules_do_not_allow_is_dropped(db: Database) -> None:
    assert resolve(db, thumbnailUrl="https://evil.example/a.jpg")["coverUrl"] is None


def test_a_song_with_a_video_and_no_picture_at_all_shows_the_thumbnail_of_its_video(db: Database) -> None:
    """P1-26: the last resort, so a song YouTube knows is never a letter tile, with no re-import needed."""
    ref = resolve(db, videoId="abcdefghijk")
    assert ref["coverUrl"] == "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg"


def test_the_order_of_pictures_is_the_cover_then_the_sources_thumbnail_then_the_videos_own(db: Database) -> None:
    both = resolve(db, title="Both", videoId="abcdefghijk", coverUrl=COVER, thumbnailUrl=THUMB)
    thumb_only = resolve(db, title="Thumb only", videoId="bcdefghijkl", thumbnailUrl=THUMB)
    assert both["coverUrl"] == COVER
    assert thumb_only["coverUrl"] == THUMB
    assert resolve(db, title="No video")["coverUrl"] is None, "no video, no thumbnail"
