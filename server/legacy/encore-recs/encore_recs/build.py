"""One person's recommendations, made from that person's own listening (docs/47 sections 1b and 4).

Nothing here learns or predicts. The knowledge is other people's: who listens to what is public (ListenBrainz), what an artist's best-known
songs are is public (Deezer), what has come out is public (MusicBrainz). This code only counts: which of *this person's* artists to ask
about, which answers to keep, and in what order to show them. The same input always gives the same list (a person's lists do not
reshuffle when they are opened twice); the only randomness is a shuffle seeded by the person and the day.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from .library import Library, Seed
from .sources import Sources
from .textnorm import norm_artist, norm_title

DAY = 86400.0

SEED_LIMIT = 40
#: Fewer signals than this (about a dozen plays or a few likes) and the honest answer is "play a few songs first", not a random list.
MIN_TOTAL_WEIGHT = 12.0
NEIGHBOURS_PER_SEED = 25
CANDIDATES = 30
POOL_CANDIDATES = 60
MADE_FOR_YOU = 30
PER_ARTIST = 3
POOL_SIZE = 100
BECAUSE_ROWS = 5
FRESH_DAYS = 45


@dataclass
class Hidden:
    """What a person said "not for me" to: artists, and single songs."""

    artists: set[str] = field(default_factory=set)               # normalised artist names
    songs: set[tuple[str, str]] = field(default_factory=set)     # (normalised artist, normalised title)

    def blocks(self, artist: str, title: str | None = None) -> bool:
        a = norm_artist(artist)
        return a in self.artists or (title is not None and (a, norm_title(title)) in self.songs)


@dataclass
class Result:
    state: str                       # "ready" or "empty" (not enough listening yet)
    rows: list[dict] = field(default_factory=list)
    pool: list[dict] = field(default_factory=list)
    releases_seen: set[str] = field(default_factory=set)   # MusicBrainz ids of fresh releases the person has now been shown
    seeds: int = 0


def _song(track: dict, reason: str) -> dict:
    return {"title": track["title"], "artist": track["artist"], "album": track["album"], "durationS": track["duration"], "reason": reason}


def build(person: str, seeds: list[Seed], library: Library, sources: Sources, hidden: Hidden, seen_releases: set[str], now: float) -> Result:
    """Raises `Throttled` (from [sources]) when a public service says "slow down": the caller keeps the last list and tries again later."""
    seeds = sorted(seeds, key=lambda s: -s.weight)[:SEED_LIMIT]
    if sum(s.weight for s in seeds) < MIN_TOTAL_WEIGHT:
        return Result("empty", seeds=len(seeds))
    rng = random.Random(f"{person}:{time.strftime('%Y-%m-%d', time.gmtime(now))}")
    top_weight = seeds[0].weight

    # 1. who the seeds are (a tagged id, or a name the catalogue knows for certain; an uncertain name is skipped)
    mbids: dict[str, str] = {}
    for seed in seeds:
        mbid = seed.mbid or sources.musicbrainz_artist(seed.artist)
        if mbid:
            mbids[norm_artist(seed.artist)] = mbid
    seed_names = {norm_artist(s.artist) for s in seeds}

    # 2. neighbours: artists whose listeners overlap, each credited to the seeds that point at it
    scored: dict[str, dict] = {}
    per_seed: dict[str, list[tuple[float, str]]] = {}  # each seed's own neighbours, best first (for its "Because you play" row)
    for seed in seeds:
        mbid = mbids.get(norm_artist(seed.artist))
        if not mbid:
            continue
        similar = sources.similar_artists(mbid)[:NEIGHBOURS_PER_SEED]
        best = max((a["score"] for a in similar), default=0.0) or 1.0
        for artist in similar:
            key = norm_artist(artist["name"])
            if key in seed_names or hidden.blocks(artist["name"]) or library.has_artist(artist["name"], artist["mbid"]):
                continue
            slot = scored.setdefault(key, {"name": artist["name"], "mbid": artist["mbid"], "score": 0.0, "because": []})
            share = (seed.weight / top_weight) * (artist["score"] / best)
            slot["score"] += share
            slot["because"].append((share, seed.artist))
            per_seed.setdefault(norm_artist(seed.artist), []).append((artist["score"], key))
    ranked = sorted(scored.values(), key=lambda c: (-c["score"], c["name"]))[:POOL_CANDIDATES]
    for candidate in ranked:
        names = [name for _, name in sorted(candidate["because"], key=lambda b: (-b[0], b[1]))]
        candidate["reason"] = "Because you play " + (" and ".join(names[:2]) if len(names) > 1 else names[0])

    # 3. songs for the best of them (a song they already have is not new; one they said no to is never shown)
    songs: dict[str, list[dict]] = {}

    def songs_of(name: str, reason: str, count: int) -> list[dict]:
        key = norm_artist(name)
        if key not in songs:
            deezer = sources.deezer_artist(name)
            songs[key] = sources.deezer_top(deezer) if deezer else []
        return [_song(t, reason) for t in songs[key] if not library.has_song(t["artist"], t["title"]) and not hidden.blocks(t["artist"], t["title"])][:count]

    made: list[list[dict]] = []
    for candidate in ranked[:CANDIDATES]:
        picked = songs_of(candidate["name"], candidate["reason"], PER_ARTIST)
        if picked:
            made.append(picked)
    made_for_you = _interleave(made, MADE_FOR_YOU)

    # 4. "Because you play X": the best neighbours of each of the person's strongest artists
    rows: list[dict] = []
    if made_for_you:
        rows.append({"id": "made-for-you", "title": "Made for you", "kind": "songs", "items": made_for_you})
    used: set[str] = set()  # an artist is suggested in one row only, so the rows do not repeat each other
    for seed in seeds[:BECAUSE_ROWS]:
        own = sorted(per_seed.get(norm_artist(seed.artist), []), key=lambda p: -p[0])
        mine = [scored[key] for _, key in own if key not in used][:8]
        if len(mine) >= 3:
            used.update(norm_artist(c["name"]) for c in mine)
            items = [{"artist": c["name"], "reason": f"Because you play {seed.artist}",
                      "topSong": next(iter(songs_of(c["name"], c["reason"], 1)), None)} for c in mine]
            rows.append({"id": "because-" + norm_artist(seed.artist).replace(" ", "-"), "title": f"Because you play {seed.artist}", "kind": "artists",
                         "items": items})

    # 5. deeper cuts: songs of artists they love that they do not have yet
    deeper: list[list[dict]] = []
    for seed in seeds[:6]:
        picked = songs_of(seed.artist, f"More from {seed.artist}, songs you do not have yet", 3)
        if picked:
            deeper.append(picked)
    deeper_cuts = _interleave(deeper, 15)
    if deeper_cuts:
        rows.append({"id": "deeper-cuts", "title": "Deeper cuts", "kind": "songs", "items": deeper_cuts})

    # 6. new from the artists they love (told once: `isNew` is false for a release the person has been shown before)
    since = time.strftime("%Y-%m-%d", time.gmtime(now - FRESH_DAYS * DAY))
    releases, shown = [], set(seen_releases)
    for seed in seeds[:30]:
        mbid = mbids.get(norm_artist(seed.artist))
        if not mbid or hidden.blocks(seed.artist):
            continue
        for release in sources.fresh_releases(mbid, since)[:2]:
            releases.append({"artist": seed.artist, "title": release["title"], "date": release["date"], "type": release["type"],
                             "isNew": release["mbid"] not in seen_releases})
            shown.add(release["mbid"])
    if releases:
        rows.append({"id": "new-releases", "title": "New from artists you love", "kind": "releases",
                     "items": sorted(releases, key=lambda r: r["date"], reverse=True)})

    # 7. the pool smart shuffle draws from: a hundred songs left by the night's build, so the phone needs no live call
    pool_lists = [songs_of(c["name"], c["reason"], 2) for c in ranked[:POOL_CANDIDATES]]
    pool = _interleave([p for p in pool_lists if p], POOL_SIZE)
    rng.shuffle(pool)
    return Result("ready", rows, pool, shown, len(seeds))


def _interleave(lists: list[list[dict]], limit: int) -> list[dict]:
    """One song from each list in turn, so two songs by the same artist are never next to each other."""
    out: list[dict] = []
    depth = 0
    while len(out) < limit and any(depth < len(l) for l in lists):
        for items in lists:
            if depth < len(items) and len(out) < limit:
                out.append(items[depth])
        depth += 1
    return out
