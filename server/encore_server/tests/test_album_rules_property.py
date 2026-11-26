"""N-34, the two rules of 25 Nov 2026 as ONE invariant, stated against GROUND TRUTH and never against the matcher's own fold.

**The invariant.** A `matched` verdict never (1) has an ELIGIBLE competitor of the same tier (album or EP), of another release family, with no compilation title, that it beat only on
the date order, and never (2) comes from a SOLE album-type release (one release family among the eligible releases of the hits, and that release an album). Both are about a stamp that
is PERMANENT: the catalogue's dates of old releases are reissue dates and placeholders, and eight hits cannot prove that no other album carries the song.

The generator knows what every release IS (its family, its type, whether it is eligible, whether its title says compilation): releases are made of a base title plus a random edition label
(the labels the rule folds) and a random date from a pool that holds year-only placeholders, missing dates and equal dates. So when the matcher's fold misses a label this fails
(the family is the generator's, not `release_family`'s), and the reasons are checked from the other side too: `date_decided` only where such a competitor exists, `sole_album` only where
there is one family.
"""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from encore_server.album_finder import choose_release
from tests.album_world import Rel, world

# The bases include what the review of PR 130 found (symbol-only titles, label-only titles, a year as the whole title): the generator knows each is its own release.
BASES = [
    "Harbour",
    "Moorings",
    "Tidewater",
    "Lanterns",
    "Foghorn",
    "Saltmarsh",
    "Driftwood",
    "Kelpwood",
    "\u00f7",
    "+",
    "=",
    "!!!",
    "Deluxe",
    "Remastered",
    "2001",
    "1989",
]
# Bases that are themselves made of label words or a year: with an UNBRACKETED label after them the narrow fold cannot tell the base from the label ("Deluxe 10th Anniversary Edition" is all
# label), so it holds the song (a delay, the safe direction). The forward checks (a stamp is never wrong) still run on them; only the reverse check ("the hold was justified") does not.
SYMBOL_BASES = {"\u00f7", "+", "=", "!!!"}
LABEL_LIKE_BASES = {"Deluxe", "Remastered", "2001", "1989"}
# Labels the NARROW list knows (the rule is exact about them) and labels it has never seen (the rule must fail CLOSED about them: a hold, never a stamp).
UNLISTED_LABELS = [
    " (Tour Edition)",
    " (Reissue)",
    " (Collector's Edition)",
    " - Japan Edition",
    " (Platinum Edition)",
    " Japanese Version",
]
LABELS = [
    "",
    "",
    " (Deluxe Edition)",
    " (20th Anniversary Edition)",
    " [Bonus Edition]",
    " (Expanded Edition)",
    " (Remastered 2011)",
    " (2005)",
    " 10th Anniversary Edition",
    " (Explicit)",
    " (Clean)",
    " (International Version)",
    " [Edited Version]",
    " (Super Deluxe Edition)",
]
DATES = [
    None,
    "0000-00-00",
    "1998-01-01",
    "1998-03-04",
    "2001-01-01",
    "2001-09-09",
    "2004-01-01",
    "2004-01-01",
    "2010-12-31",
    "2019-07-08",
    "2019-07-08",
]
COMPILATION_PREFIXES = ["Greatest Hits of ", "The Best Of ", "Collection ", "Gold ", "Singles ", "Ultimate "]


@dataclass(frozen=True)
class Made:
    rel: Rel
    family: int  # the generator's own label of "which release this is"
    eligible: bool
    compilation: bool
    listed: bool = True  # every label of this release is one the narrow list knows


@st.composite
def catalogues(draw: st.DrawFn) -> list[Made]:
    count = draw(st.integers(1, 4))
    bases = draw(st.permutations(BASES).map(lambda order: order[:count]))
    made: list[Made] = []
    number = 0
    for family, base in enumerate(bases):
        # A symbol base is a whole title on its own ("÷", "+"); beside a word ("Gold ÷" and "Gold +") the shared `catalogue.release_key` drops punctuation BY DESIGN and makes them one release, which
        # is not something the generator's ground truth may call two. So a symbol base is never given a prefix word.
        compilation = (draw(st.booleans()) and draw(st.booleans())) and base not in SYMBOL_BASES
        foreign = not compilation and draw(st.integers(0, 5)) == 0
        live = not compilation and not foreign and draw(st.integers(0, 6)) == 0
        title = (draw(st.sampled_from(COMPILATION_PREFIXES)) if compilation else "") + base + (" (Live)" if live else "")
        for _ in range(draw(st.integers(1, 3))):
            number += 1
            record = draw(st.sampled_from(["album", "album", "ep", "single"]))
            label = draw(st.sampled_from(LABELS + UNLISTED_LABELS if draw(st.integers(0, 3)) == 0 else LABELS))
            rel = Rel(
                str(100 + number),
                title + label,
                record,
                draw(st.sampled_from(DATES)),
                artist="Somebody Else" if foreign else None,
            )
            made.append(
                Made(
                    rel,
                    family,
                    eligible=not foreign and not live,
                    compilation=compilation,
                    listed=label not in UNLISTED_LABELS and base not in LABEL_LIKE_BASES,
                )
            )
    return made


def _facts(made: list[Made], matched_id: str) -> tuple[Made, list[Made], int]:
    chosen = next(m for m in made if m.rel.id == matched_id)
    competitors = [
        m
        for m in made
        if m.eligible
        and not m.compilation
        and m.family != chosen.family
        and m.rel.type in ("album", "ep")
        and chosen.rel.type in ("album", "ep")
    ]
    families = len({m.family for m in made if m.eligible})
    return chosen, competitors, families


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(catalogues(), st.randoms(use_true_random=False))
def test_a_matched_verdict_has_no_date_competitor_and_is_not_a_sole_album_and_each_reason_is_true(
    made: list[Made], random
) -> None:  # type: ignore[no-untyped-def]
    order = list(made)
    random.shuffle(order)  # the hits come in any order
    song, hits, answers = world(*(m.rel for m in order))
    verdict = choose_release(song, hits, answers)
    if verdict.outcome == "matched":
        assert verdict.match is not None
        chosen, competitors, families = _facts(made, verdict.match.album_id)
        assert chosen.rel.type in ("album", "ep"), "a single is never stamped"
        assert competitors == [], (
            f"{chosen.rel.title!r} was chosen though {[c.rel.title for c in competitors]} compete with it on the date alone"
        )
        assert not (chosen.rel.type == "album" and families == 1), "a sole album is never stamped"
    elif (verdict.outcome, verdict.reason) == ("none", "date_decided") and all(m.listed for m in made):
        # (a label the narrow list has never seen may hold a song the ground truth would stamp: that is the safe direction, so only checked when every label is known)
        assert verdict.withheld is not None
        _, competitors, _ = _facts(made, verdict.withheld.album_id)
        assert competitors, "date_decided said no competitor exists"
    elif (verdict.outcome, verdict.reason) == ("none", "sole_album") and all(m.listed for m in made):
        # (the broad comparison may call two releases one - "Gold Deluxe" and "Gold Remastered", or an unseen label - and hold the song: the safe direction, so the reverse check runs only on
        # worlds whose labels and bases are unambiguous)
        assert verdict.withheld is not None
        chosen, competitors, families = _facts(made, verdict.withheld.album_id)
        assert chosen.rel.type == "album" and families == 1 and not competitors, (
            "sole_album said there was a second release family"
        )
