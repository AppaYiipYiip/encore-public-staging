# 19 — Song identity, matching, search, and fixing wrong songs

> **In short.** The specification of song identity: how two descriptions are decided to be the same song (normalisation, matching rules), how search ranks, how a wrong song is fixed and how duplicates merge. **Built:** the matching and ranking that picks a YouTube upload (`sources/youtube/scoring.py`) and refs found by ISRC, video id or normalised key. **Not built:** the Unicode normalisation of section 2 (the server folds to ASCII, B-37, P2-25), the server's catalogue search (section 4, P2-12), "Wrong song?" (section 5, P4-14) and the merge of refs (section 6, B-71).

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

> **Built, not walked (P2-25 slices 2 and 3, audit B-37; 16 Nov 2026).** Before, the server's `textnorm` folded to ASCII: every Arabic, Cyrillic, Korean or Japanese letter was dropped (a name made only of them was the empty string, a name that started in Latin was cut at its Latin part), the Latin letters that do not decompose (`ø ł ı ß đ æ`) were dropped too, different songs merged into one and an exact non-Latin match from YouTube Music was rejected. Now ONE fold, written once in `textnorm.py`, is used by every place of the server that compares text (the song key, the music server's `pick_song`, the keeper's folders and `find_existing`, the cover and artist-picture finders, the YouTube matcher, N-26's upload reading, the release editions of the catalogue); the phone's twin is `app/lib/domain/text_fold.dart`, and `app/test/fixtures/text/fold-cases.json` is the one fixture both read. The design (why each row, what is kept apart on purpose, the repair of databases already built) is `tasks/P2-songs-as-references.md`, section P2-25. **Still open: slice 4** (the library link moves the files that the old fold glued onto the wrong song) and the phone's own matcher (`normalizeForMatch`, B-46, P2-12 slice 8).

**The fold, in the order the code does it (`textnorm.fold`; punctuation and spaces are KEPT, `words` cuts them):** (6) invisible format characters (the bidirectional marks, the joiner, the soft hyphen, the byte order mark) are removed with no gap, and the zero-width NON-joiner (the Persian half-space) becomes a space, as Lucene's `PersianCharFilter` has it; (1) NFKC (fullwidth Latin, halfwidth katakana, Arabic presentation forms, ligatures; never NFKD, which splits Hangul and the voiced kana); (2) case fold (`ß` is `ss`, final sigma is sigma); (3) the DECORATING marks are removed, by an allow-list (the combining diacritics, the Arabic harakat and Quranic marks, the Hebrew points): the marks of Devanagari, Thai, the Japanese voiced marks and Hangul pieces are KEPT, so a Hindi phrase stays two words and `が` is not `か`; (4) letters with no decomposition: `ø→o ł→l đ ð→d þ→th æ→ae œ→oe ı→i ħ→h ŧ→t`; Arabic alef forms `آ أ إ ٱ→ا`, `ى ی ے→ي`, `ک→ك`, `ة ۀ ہ→ه`, the tatweel removed; Cyrillic `ё→е`; **kept apart on purpose**: `й ї ў` (`мой` and `мои` are two words), the hamza seats `ؤ ئ ء`; (5) every decimal digit of any script becomes its ASCII digit. The Arabic and Persian rows were checked against the sources of Lucene release 10.3.2 (`ArabicNormalizer`, `PersianNormalizer`, `PersianCharFilter`: every case is a test row; this fold is a superset; nothing else of Lucene was compared). The fold is pinned to Unicode 15.0.0 (the Python of the server image) and the stored keys carry a revision (`setting.textnorm_revision`): see `18`.

1. The fold above (Unicode NFKC, case-fold, the decorating marks, the letters with no decomposition, ASCII digits).
2. What the IDENTITY key does NOT do (it never guesses): it keeps "the", "and" and `&`; looser rules (a leading "the", `&` as `and`, the edition suffix of a release, typo forgiveness) belong to the comparison layer a client types against, on top of the same fold (`catalogue.release_key`, P2-12).
3. The Arabic, Persian and Urdu rows are step (4) of the fold above.
4. Split **featured artists** out of titles and artist strings (`feat.`, `ft.`, `featuring`, `with`, `x` between names, `&` lists; also the Arabic comma and semicolon `،` `؛` and the ideographic comma `、`; the words for "and" in other scripts are NOT separators).
5. Pull **version tags** out of brackets into a separate field: live, acoustic, remix (with remixer), remaster(ed) (year), radio
   edit, extended, instrumental, karaoke, cover, sped up/slowed, demo, explicit/clean, deluxe/bonus. The list of words is English; per-language lists are data, added on the evidence of N-16. The brackets Japanese and Chinese titles put their tags in (`【】`, `〔〕`) count; the corner brackets that QUOTE a song's name (`「」 『』`) do not.
6. Remove punctuation; keep digits. **No part of the key is ever empty while there is something to read**: a title that is only a noise word (`Audio`) keeps its words, a name of only symbols (`!!!`) keeps itself, so `???` and `!!!` are two songs.
**Short names in a dense script (Han, Kana, Hangul) are compared for EQUALITY up to four characters** (`textnorm.ratio`): one syllable off is another word, not a typo (`사랑해` against `사랑이` was 0.667 by characters, above the 0.6 title bar). Longer ones keep the thresholds until the 40 real searches of N-16 measure them. `MATCHER_REVISION` is 2.
`norm_key` = normalised primary artist + normalised base title + the version words of its brackets (`artist|title|version`, built by `refs.norm_key`); the length is not in the key: a lookup accepts a ref whose length is within 3 s (`refs.DURATION_TOLERANCE_MS`).

## 3. Matching rules (is candidate C the song S?)

| Evidence | Verdict |
|----------|---------|
| Same ISRC, or same YouTube video id, or same MBID | **certain** |
| Primary artist matches (normalised, or via an alias), base title similarity ≥ 0.9, same version tags, duration within ±3 s | **strong** → accept |
| Same, but duration within ±10 s or one version tag differs (remaster) | **weak** → accept for play, flag for keep (the keeper re-checks with a second source) |
| Version differs in kind (live vs studio, remix vs original, karaoke/cover/sped up) | **reject** unless the person asked for that version |
| Primary artist does not match | **reject** ("Animals" by Pink Floyd ≠ Animals as Leaders) |
**The plain path holds the same line (N-44, audit B-136, 26 Nov 2026).** An upload seen only by its title, its channel and its length (a video result) needs the TITLE as much as the artist and the length: before, another song of the artist's own channel at the same length scored 7.5 and was kept under the right name (a permanent wrong identity). The wanted title must be the upload's title word by word and in order (the weakest word at least 0.7 alike, so one song spelled two ways passes and "Hurt" is not "Hurt Me"), or the same letters with the spaces and dots moved (0.9), or inside a longer title with nothing else of the song left; **long content** (20 minutes or more) of the wanted length to the second is taken whatever else its title says (a recitation). A short dense-script name is found only as a whole word. Known limits, pinned in `tests/sources/test_plain_match_title.py`: a part number written two ways ("Pt. II", "Pt. 3") is one song to a title bar; a title that is only a bracketed phrase folds to nothing and is found as a song result or not at all.
Prefer YouTube Music **song** results (official "Topic"/art tracks) over music videos (intros, skits, censored edits); use videos for
long content (recitations, DJ sets, podcasts) and when no song result passes. Explicit vs clean: follow the source's flag, and the
person's setting (`21` §5).

**Who is the artist of an imported upload (N-26; code `imports/uploads.py`, the one door both playlist readers go through).** This is not matching
(nothing is searched): it decides which artist a song of a pasted YouTube playlist is filed under. **The channel is the uploader, and the uploader is
evidence, not the artist**: for an upload by a person or an organisation YouTube Music lists the uploading channel as the "artist" ("Tinariwen - Full
Performance (Live on KEXP)" is credited to KEXP). Each song gets its artists and a **basis**, how that was decided:

| What the source says | The artist is | Basis |
|----------|---------|-------|
| `videoType` ATV or OFFICIAL_SOURCE_MUSIC (YouTube's own audio of a song); an entry with no `videoType` that has an ALBUM (a removed catalogue song keeps its album; an entry that is merely unavailable proves nothing, a removed upload is unavailable too); a "- Topic" channel (yt-dlp); a Spotify or file description | the artists the source gives ("- Topic" and "VEVO" stripped) | `declared` |
| `videoType` OMV (an official music video) | the credited artists, **unless the title names a different performer before a separator** ("Band - Song" under a label's credit: the band, basis `title`). A title that says the credited name anywhere, has no separator, or has a side that only describes the upload or the version ("Song - Official Video", "Song - Live in Moscow") keeps the credit | `declared` (`title` when read from the title) |
| `videoType` UGC, **any value this code does not know**, an available entry with no `videoType` and no album, or yt-dlp's flat listing | a title with a separator (a hyphen, any dash, the minus sign, the middle dot or the bullet, spaces on both sides, outside brackets) is `Artist - Song`; the uploader flips it to `Song - Artist` only when it is a **whole name** of the right side (compared in any alphabet, never as a substring: "kexp" is inside "(Live on KEXP)"). A bracket never decides who the artist is. One shape of context is read besides the separator: a first segment that ends in the word Opening or Ending (with an optional number) followed by a pipe (never a dash) and `<Song> by <Artist>` with exactly one "by" ("DAN DA DAN Opening \| Otonoke by Creepy Nuts": the artist after the "by", the song before it, the series dropped; a label that is the uploader's own name, a separator before the pipe, a second "by" or a credit with a bracket, pipe or quote left in it names nobody). A bare "by" and the abbreviations OP and ED are not read: they break "Stand By Me", "Nocturne Op. 9" and "Ed Sheeran" (`tests/fixtures/n26_upload_corpus.json`: no rule is accepted that changes a row that is right today) | `title`; `channel` when the artist is reached only because the right side IS the uploader's name |
| an upload whose title names nobody | the uploader, as YouTube Music shows it (**the one stop-gap**, removal trigger N-28: the catalogue names the artist of a song by its title) | `channel` |
| nothing names anybody (an official video with an empty credit) | none: the importer files the song under "Unknown Artist" (the name the keeper's folders already use: `textnorm.UNKNOWN_ARTIST`) | `unknown` |

**"Unknown Artist" is a placeholder, not a name: it has no identity.** A song whose artist is that is found by its ids (video id, ISRC, catalogue id) and never by artist + title + length, because the name of two different nameless songs is the same string (`refs.find` skips the name lookup, live refs and merge tombstones alike, for it; the N-11 repair merges only refs that hold one file and holds two that name different videos, so it cannot merge them either), and no catalogue is asked about it (`artist_finder`). The same holds for a real artist literally called "Unknown Artist": a name that cannot be told from "nobody" identifies nothing. The cost, accepted: a description with the placeholder and no id at all is not found again (an import always has its video; the library scan finds a file's ref by the file first). Only `declared` and `title` are performers; the picture and page guards of N-26 slices 2 and 3 key on the basis. Unknowable from YouTube alone, and written down
rather than hidden: a personal account whose title names nobody looks the same whether it is the band's own or a stranger's; an official video credited to a
label with no separator in its title; which side is the artist when neither is the uploader; whether `<Artist>, live at <Venue> – <Channel>` names the performer or is a song the performer uploaded (a broadcaster and a performer look the same: not read, left to N-28).

## 4. Search (`GET /encore/api/v1/search?q=`; planned, P2-12: the route does not exist yet, `17` section 3)

* **Phone first, instantly:** the person's own library from the phone's database (full-text, ≤ 50 ms), shown at once, offline too.
* **Server, two phases:** `phase=fast` answers within ~400 ms from the cache, the server's files and Deezer; `phase=full` adds
  YouTube Music results (regional, independent, long content) when they arrive (≤ 1.5 s). The app shows fast results and merges the
  full ones without the list jumping under the finger (new items appear below, the Top result only changes if nothing was tapped yet).
* **Ranking:** a Top result (exact normalised artist + title, else best match of the query's intent: an artist, an album), then Songs
  (match quality, then owned/kept first, then popularity), Artists, Albums, Playlists, like Spotify. **An answer that is only partial
  never ranks as high as an exact one** (P1-07, `app/lib/domain/search_rank.dart`, which holds the scale): an artist whose name is exactly
  what was typed is the Top result over every song or album that merely starts with or contains the words (typing "jinjer" gives the
  band, not a song titled "Jinjer - Pisces"); a song or an album that is itself exactly the typed words takes that place only when the
  artist is barely known (not in the library and under 50,000 fans: typing "Hotel California" means the song). Popularity only settles
  that tie (one exception: a row with no releases at all, a collaboration or a namesake, is ranked after the real artist and, when it is
  also barely known, can fall below a partial song). The server's one ranked list (P2-12) keeps this rule.
* **A title that begins with an artist's name (P1-07, 15 Nov 2026):** a song saved from an upload before N-26 kept the uploading channel as its artist, with the band only at the start of its title ("LANDMVRKS - CONCERT 4K - ..." by "slash musique"). When the words before the first spaced dash are exactly the name of an artist that the library has, or a catalogue artist the person has or with at least 50,000 fans (a namesake with a handful of fans does not count: Deezer lists an artist called "Hotel California" with 7,812), the LIBRARY's song is scored as BY that artist (the name is an artist word, the rest is the title), so a half-typed band name ("landmvrk") gives the band, not an upload that repeats its name. The catalogue's own songs are never reread (Deezer names the real artist); a library song such as "Hotel California - Live at the Forum" by Eagles is a song with a suffix and keeps its score; with no such artist nothing changes. `test/features/search_recorded_top_test.dart` pins what the 20 recorded searches show through the whole assembly. It is a second layer over the stored rows and stays right after N-26 slice 5 has refiled them (`search_rank.dart` `_leadingArtist`, `search_assembly.dart`). The server's one ranked list (P2-12) must keep it until then.
* **A typo in an artist's name (N-23a):** the phone's own search of the library only matches the start of a word, so it cannot find
  "landmarks" for the band "Landmvrks". When **no artist of the library begins with the typed words**, the phone scans the library's artist
  names (a few thousand, folded once; about 2 ms for 5,000) for one that is a typo: **both have 5 or more letters and one letter is wrong,
  missing, extra or swapped with its neighbour (two from 9 letters on); a name of 1 to 4 letters is never guessed**
  (`app/lib/domain/artist_typo.dart`). **A name that is not finished yet counts too** (owner, 15 Nov 2026: "landmrvk" for "Landmvrks", a swap and no last letter): what was typed is compared with the same number of letters from the START of the name (one fewer or one more allowed), by the same allowance (`typoEditsOfStart`; only for a name longer than what was typed). Such an artist scores 0.6 (`typoArtistScore`): below every exact answer and the start of a name, so it
  is the Top result only when nothing answers better. This is the phone matching only what is on the phone (audit B-46): the catalogue's
  typos are Deezer's own matching through the server (N-23b); the server has no search of the library.
* **The library's answer is never held back (P1-07, 14 Nov 2026):** what the phone's own full-text search finds is drawn as soon as it is found: not after the catalogue (Deezer) has answered or failed, and not delayed or started over by anything written to the library meanwhile (a sync page, the server's own row; found: on a busy phone a sync writing every 100 ms kept the page empty for the whole sync). The catalogue's rows and the typo guess are added to it when they arrive and take none of it away. In code `_ftsSearchProvider` watches only the server id and the database, `searchResultsProvider` adds the guess (the list of artists is watched only there), and `app/test/features/search_local_first_test.dart` guards it (a catalogue that never answers, one that answers late, a sync writing every 100 ms on a database that answers at once and on a busy one).
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

* **Not built (register B-71):** refs with the same ISRC, video id or MBID are meant to be merged automatically (likes, entries and history move to the surviving ref in one
  transaction; the merge is logged). Today `refs.find` returns the first match and two refs for one recording stay two.
* Files: one ref with several files keeps the best one as preferred; the others are listed in Admin → Library → duplicates (`15` section 4) with their
  size and a "Remove extra copies" button (owner decision D-2: one copy per song); nothing is deleted without the Host's click.

## 7. Tests (P2-01, P1-07)

A labelled set of ≥ 200 real pairs (title/artist as people type them, Spotify exports, YouTube titles) covering Arabic, French,
Japanese, featured artists, remasters, live/studio, covers, same-title-different-artist; the matcher's precision on "accept" must be
≥ 99 % and recall ≥ 90 %. The set grows with every "Wrong song?" report (anonymised: only titles and the chosen answer).
