# N-38: a song whose tags the server rewrites stays downloaded on the phone

*Status: SERVER HALF built (27 Nov 2026; built, not walked). PHONE HALF owed (specified below; needs the app suite). Trigger that makes it urgent: BEFORE any repair that rewrites the tags of kept files ships (N-34, N-26 slice 5). Rule 1 of the standing rules: the cost of the quick answer (every repair makes every phone fetch every repaired song again) is a cost to the future, so this is built first.*

## 1. The problem, with the proof

A phone marks a downloaded song stale when the key it stored at download time differs from the live one (`download_planner.dart`: `row.sourceAudioKey != want.audioKey`). For a song the Encore server keeps, the live key is `refAudioKey(ref)` (`fingerprint.dart`), a hash of `file.size`, suffix, bitrate, duration, sampling rate and bit depth. **The size is the problem**: a rewrite of a file's tags (a new cover, a new album artist, a repair) changes it, the music server's next scan reports the new size, the phone's next sync stores a new key, and the planner schedules the whole song again. The person hears nothing different and may be on mobile data. The ruling of 15 Nov 2026 (advisor, on the N-34 design) accepted ONE such re-download for N-34 and ordered this fixed before a second repair: every later retag would otherwise pay it again.

The size is there for a reason (a replaced or re-encoded file must be fetched again), so it cannot just be dropped: duration in whole seconds, bitrate and sample rate do not tell two CBR rips of one length apart.

## 2. The answer: the key is of the audio stream, made by the server

`encore_server/audio_key.py`. `a1:` + the first 32 hex digits of the SHA-256 of the file's **first audio stream copied as it is** (`ffmpeg -map 0:a:0 -c copy -f hash -hash sha256 -`): the compressed packets; never the tags, the cover (a video stream, not mapped), the container's pages or boxes.

* **Proved** on the real ffmpeg (`tests/integration/test_audio_key.py`, the `encore-server-navidrome` CI job): for Opus, FLAC, AAC in MP4 and MP3 the key is the same after the keeper's own tag writer added a cover, after an ffmpeg remux with other tags, and for a byte copy; it differs for another tone, another length and another encode of the same recording; a file that is not audio is `Unreadable`.
* **FROZEN.** A phone keeps the key it was served in every download for as long as the download lives. A new way of making it would change every key at once, which is the mass re-download this prevents. A new way is a new prefix (`a2:`) and a phone-side migration (section 4); the prefix says which way made a key and a phone never compares two prefixes.
* **Stored** in `song_file.audio_key` with the size the key was taken at (`audio_key_size`), migration 0022. `NULL` = not made yet; `''` = ffmpeg cannot read the file at that size (served as no key; looked at again only when the size changes).
* **Served** as `file.audioKey` in the ref (`GET library/files`, `GET refs/{id}`...): additive, optional, ABSENT (not null) when there is none. An app from before it ignores it; a server without it serves none and the phone does what it did.

### When a key is made

| Moment | Who | Notes |
|---|---|---|
| A new keep | the keeper (`keeper._link`), from the file as it lies, tagged and placed | a key that cannot be made (`Unreadable`, no ffmpeg, a timeout) never fails a keep; the hourly errand makes it |
| A file the library link found (an imported library, a file put there by hand) | `AudioKeys.run_once`, an errand of the hourly library link | at most 400 files and 40 seconds a pass, preferred files first, `nice -n 10`; a library is keyed over a few passes |
| A file whose size changed behind the server's back (the music server's `meta.size` is not the size the key was taken at) | the same errand | hashed again; **if the key is the same nothing is told to any phone** (only the size it is recorded at moves) |
| The server's OWN tag rewrite (a repair) | the repair, by `audio_key.carry(conn, file_id, new_size)` in the transaction that records the rewrite | records the new size against the SAME key (and in the row's `meta.size`, in the format a scan writes, so the errand does not take the file for one that changed behind the server's back): no second hash, so a new ffmpeg version (the image is rebuilt weekly) can never move a key phones hold. **A repair that forgets costs the hashing and, after an ffmpeg upgrade, could move a key**: that is why section 3 makes the repair PR's own test enforce it |

**While a key is out of date the last known key is served, never none**: a replaced file shows its new key within an hour (the next pass); a file the server retagged keeps the key it had. A phone is told a key through the files feed (`file_log`) only when the key SERVED is new or different.

### Costs, said plainly

* One ffmpeg process per file (about the time to read it: tens of milliseconds a song, a few hundred to ten minutes of one-time work for a library of 10 000 songs, spread over passes).
* **Fairness and races** (review of #164): every file the errand tried and did not key (not found, changed while read, stopped it) is stamped `audio_key_tried_at` and goes behind the files it has never looked at, so a file that is never found or always times out cannot keep the others from their turn; a key is written only if the row is still as the pass read it (a keeper that linked the same file meanwhile is not overwritten with an older answer).
* **Paths** (review of #164): a `song_file.path` the keeper made, and a relative one from the music server, is relative to the music folder and is taken as it is; one the music server reports as ABSOLUTE or with its own library root in front is looked for by its tail (the longest tail that is a file under the music folder; never `..`). Proved against the real music server in the integration job (a file whose folder and name disagree with its tags).
* One query over `song_file` an hour (a scan of the table: `json_extract(meta, '$.size')` against `audio_key_size`; the same order as the library link's own pass).
* One `file_log` row per key made or changed (the feed is never pruned: about 100 bytes a file, once).
* A file ffmpeg cannot read has no key: the phone keeps the old behaviour for that song (size in the key), so a retag of it re-downloads once. Bounded and visible in the log (`no audio key for ...`).

## 3. What the repair slices owe (the rule this item creates)

A PR that rewrites the tags of files already kept (N-34's repair, N-26 slice 5, any later retag) **must**: (1) make sure every file it will rewrite HAS a key before it touches the file (`audio_key_of`, stored like the errand does), (2) call `audio_key.carry` in the transaction that records each rewrite, (3) not ship until the phone half below has been in the released app (board note on the item, walked), and (4) say in its description how many files it rewrites and which of them had no key. A test in that PR shows a rewrite leaves `file.audioKey` as it was.

## 4. The PHONE half (owed; its own PR with the app suite)

1. `EncoreFile.audioKey` (`String?`, from `file.audioKey`).
2. `refAudioKey(ref)`: when the ref has `file.audioKey` the key is that string (it starts with `a1:`); otherwise the old hash, unchanged. `Tracks.audioKey` stores what it returns, as today.
3. **Existing downloads must not be fetched again because the formula changed** (the migration, **adopt by match**). The stored `sourceAudioKey` of every download made before is the OLD hash. The planner is given the live key AND the old-formula key of the same ref (`audioKeyLegacyOf(track)` is computable from the `Tracks` columns `size`, `suffix`, `bitRate`, `durationSec`, `samplingRate`, `bitDepth`, no new column). For a `done` download:
   * stored key is the new kind (`a1:`): changed iff it differs from the live `a1:` key; **if the live key is not the new kind** (a server that stopped serving keys, a file with none) the download is NOT changed: a key from a way that cannot be computed now says nothing;
   * stored key is the old kind and the live key is the new kind: if the stored key equals the live OLD-formula key the file has not changed since the download, so the download is **current and its stored key is rewritten to the new one in place** (no fetch, no state change); if it differs the file changed (or was retagged before the key arrived): stale, as today;
   * otherwise as today.
4. The merge code (`RefMerger.settle`: "the moved downloads take the survivor's audio key") keeps working: it copies whatever key the survivor has.
5. Tests: the planner table (all rows above); a download made with the old key survives the first sync that brings `audioKey` with no fetch and the stored key is the new one afterwards; a retag after that changes `size` and not the key, and nothing is queued.
6. **Residue, said plainly**: a phone that was offline across BOTH the key's arrival and a tag rewrite compares its old-formula stored key with the live old-formula key (the size changed), finds a difference and fetches that song once. Nothing in the product can know the file was only retagged without the key; the cost is one fetch of a retagged song on a phone that was away, and it is the same cost as today.

### Rollout order (why it is safe)

1. The server with keys (this PR) is deployed: old apps ignore `audioKey`, nothing changes for them.
2. The app with the adopt rule is released. Phones sync, adopt, and from then on a tag rewrite is invisible to them.
3. Only then a repair that rewrites tags may ship (section 3).

## 5. Not here

Lyrics, covers and anything about WHAT a song's tags say are not this item. A key for the Subsonic path of the app (`audioKeyOf(SsSong)`, used when a phone talks to a plain music server) is not changed: it has no Encore server to make one.

## 6. Tests

`tests/test_audio_key.py` (27: command; parse; unreadable vs a missing program vs a timeout; serving; `attach_file` and the feed; `carry`; the errand: a library file keyed once, a foreign retag hashed again with no news, a replaced file re-keyed and told, the old key served meanwhile, unreadable marked at its size and retried when it changes, a missing file and a path that leaves the music folder never read, a file that changes while read left, a missing program stops the pass and marks nothing, the batch, the budget and the preferred file first); `tests/test_keeper.py` (a new keep carries the key of the file it placed; a key that cannot be made does not fail a keep); `tests/integration/test_audio_key.py` (the real ffmpeg, four containers, the proof of section 2, and the errand end to end).
