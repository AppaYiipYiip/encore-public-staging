# 19 — Song identity, matching, search, and fixing wrong songs

Why: "Is this the same song?" decides whether a like survives, whether an import is right, whether a Jam plays the same version on two
phones, and whether search shows what you typed. It was spread across the fetch service's scoring, the app's Deezer client and the
import code, with different rules in each. This page makes it one engine (module `catalogue`, used by search, imports, the keeper,
the Jam and recommendations).

## 1. Sources and what each is trusted for

| Source | Gives | Trusted for | Limits (be polite) |
|--------|-------|-------------|--------------------|
| The server's own files (Navidrome) | tags, ISRC/MBID if present, duration | what the Host owns | none |
| **Deezer API** (public, no key) | clean metadata, **ISRC**, album, track numbers, covers, popularity rank, previews | identity and metadata of mainstream music | about 50 requests per 5 s per address (verify); cache 7 days |
| **YouTube Music** (`ytmusicapi`) | audio-backed results (video id), "song" vs "video" type, duration, album, thumbnails | what can actually play; regional and independent music Deezer lacks; long content | shared YouTube budget (`04` §5); cache search results 24 h |
| MusicBrainz | MBIDs, artist aliases (transliterations), relations | aliases for search, tags for kept files | 1 request/s with a real User-Agent; cache 30 days |
| Spotify embed / exports | the list a person imports | the import list only | ≤ 100 songs per link |

The **phone no longer calls Deezer or LRCLIB directly** (it does today): the server's catalogue does, caches for everyone, and keeps
one ranking. Lyrics are fetched by the server too and travel with downloads.

## 2. Normalisation (one function, `textnorm`, shared everywhere)

> **Not implemented as written (audit B-37, proven 6 Nov 2026).** The server's `textnorm` folds to ASCII, so every Arabic, Cyrillic, Korean or Japanese name becomes the empty string, different songs merge into one and an exact non-Latin match from YouTube Music is rejected. The steps below are the specification; P2-25 builds them.

1. Unicode NFKC, case-fold, collapse spaces.
2. Latin: strip diacritics (Beyoncé → beyonce), `&`/`and`/`+` → `and`, drop a leading "the ".
3. Arabic: unify alef forms (أ إ آ → ا), ى → ي, ة → ه, drop tatweel and harakat; Persian/Urdu variants of ي and ك.
4. Split **featured artists** out of titles and artist strings (`feat.`, `ft.`, `featuring`, `with`, `x` between names, `&` lists).
5. Pull **version tags** out of brackets into a separate field: live, acoustic, remix (with remixer), remaster(ed) (year), radio
   edit, extended, instrumental, karaoke, cover, sped up/slowed, demo, explicit/clean, deluxe/bonus.
6. Remove punctuation; keep digits.
`norm_key` = normalised primary artist + normalised base title + duration rounded to 5 s.

## 3. Matching rules (is candidate C the song S?)

| Evidence | Verdict |
|----------|---------|
| Same ISRC, or same YouTube video id, or same MBID | **certain** |
| Primary artist matches (normalised, or via an alias), base title similarity ≥ 0.9, same version tags, duration within ±3 s | **strong** → accept |
| Same, but duration within ±10 s or one version tag differs (remaster) | **weak** → accept for play, flag for keep (the keeper re-checks with a second source) |
| Version differs in kind (live vs studio, remix vs original, karaoke/cover/sped up) | **reject** unless the person asked for that version |
| Primary artist does not match | **reject** ("Animals" by Pink Floyd ≠ Animals as Leaders) |
Prefer YouTube Music **song** results (official "Topic"/art tracks) over music videos (intros, skits, censored edits); use videos for
long content (recitations, DJ sets, podcasts) and when no song result passes. Explicit vs clean: follow the source's flag, and the
person's setting (`21` §5).

## 4. Search (`GET /encore/api/v1/search?q=`)

* **Phone first, instantly:** the person's own library from the phone's database (full-text, ≤ 50 ms), shown at once, offline too.
* **Server, two phases:** `phase=fast` answers within ~400 ms from the cache, the server's files and Deezer; `phase=full` adds
  YouTube Music results (regional, independent, long content) when they arrive (≤ 1.5 s). The app shows fast results and merges the
  full ones without the list jumping under the finger (new items appear below, the Top result only changes if nothing was tapped yet).
* **Ranking:** a Top result (exact normalised artist + title, else best match of the query's intent: an artist, an album), then Songs
  (match quality, then owned/kept first, then popularity), Artists, Albums, Playlists, like Spotify.
* **Typing:** the search screen waits 90 ms after the last key before it asks (`search_screen.dart`; this page said 250 ms), minimum 2 characters, cache per normalised query (24 h), prepare the Top result (P1-04). **OPEN (needs owner/advisor):** `03` N7 wants catalogue results at most 300 ms after the last key, but the server's fast phase is allowed about 400 ms (P2-12 acceptance: p50 at most 400 ms) and nothing measures the total, so N7 cannot hold as written: relax N7 (to about 500 ms) or cut the phase's target.
* **Transliteration:** the query is also matched against artist aliases (MusicBrainz) so "fairouz", "fairuz" and "فيروز" find
  the same artist; Arabic queries are normalised with §2.

## 5. Fixing a wrong song ("Wrong song?")

Wrong versions will happen (a live take, a clean edit, a fan upload). Today there is no way to fix one (H23).
* Any person: song menu → **"Wrong song?"** → up to 5 alternatives (title, channel/album, length, a 15-second preview) → pick one, or
  "None of these". The choice applies **server-wide at once** (it is a household server), is recorded with who made it, and the Host
  can undo it in the admin (`15` section 4; the list of "Wrong song?" fixes has no page drawn yet).
* If the song was kept, the keeper fetches the chosen version as a new `song_file`; likes and playlist places stay (ADR-R4).
* "None of these" marks the ref `unavailable` for that version and offers a manual search.
* The Host can also edit a ref's title/artist/album/cover (Admin → Music) for library-wide fixes (e.g. an album split wrongly).

## 6. Duplicates

* Refs with the same ISRC, video id or MBID are merged automatically (likes, entries and history move to the surviving ref in one
  transaction; the merge is logged).
* Files: one ref with several files keeps the best one as preferred; the others are listed in Admin → Library → duplicates (`15` section 4) with their
  size and a "Remove extra copies" button (owner decision D-2: one copy per song); nothing is deleted without the Host's click.

## 7. Tests (P2-01, P1-07)

A labelled set of ≥ 200 real pairs (title/artist as people type them, Spotify exports, YouTube titles) covering Arabic, French,
Japanese, featured artists, remasters, live/studio, covers, same-title-different-artist; the matcher's precision on "accept" must be
≥ 99 % and recall ≥ 90 %. The set grows with every "Wrong song?" report (anonymised: only titles and the chosen answer).
