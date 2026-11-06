# 34 — Conflicts and offline edits: what happens when two devices (or two moments) disagree

> **In short.** The state tables of disagreement: the life of one queued edit (`CF-1`...), what two devices of one person end up showing for every pair of operations, and other disagreements (a changed file, a repeated pull, a wrong clock). The model: local first, deliver in order, the server applies in arrival order, the feed is state-based. A waiting playlist edit is not yet protected from a pull (B-61, P2-28).

Written 2026-10-23 from the server's merge rules (`library.py`, `api.py`), the app's outbox and writer (`data/sync/outbox.dart`, `data/encore/encore_delivery.dart`,
`encore_writer.dart`), the contract `17` §5 and the tests that exist. Same reading rules as `31`: **Built** (I read the code and a test exists unless it says "none"),
**Designed**, **Open**. Where `17` says one thing and the code does another, the row says so: that is the most useful kind of row.
How the connection breaks and recovers is `31`; what stops the music is `33`.

## 1. The model in six lines

1. **Local first.** An edit changes the phone's database at once and is queued as an **operation** in the outbox (`like`, `unlike`, `create playlist`, `add songs`, `remove songs`,
   `rename`, `delete`, `play report`). The screen never waits for the network.
2. **Delivery** is in order, at least once, one engine at a time (a lease): a lost network stops the queue and keeps its order; a retry cannot make a duplicate because the phone
   makes the ids (`pe_` for a playlist entry, `pl_` for a playlist, a play report's id) and the server ignores an id it has seen.
3. **The server applies operations in the order they arrive**, each meaningful on its own, so edits of two devices of one person **merge**.
4. **The server tells every other device** through the live connection (`library.changed`), and the phone then asks for what changed after its cursor. The feed is **state-based**
   ("this like exists", "this entry is removed" as a tombstone), so a missed or repeated event ends up right (measured: 2.2 to 2.6 s, `evidence/b01`, `b02`).
5. **What waits in the outbox is never overwritten** by what the server last said: a like or unlike still waiting stays as the person left it until it is delivered.
6. Playlists belong to **one person**; nobody else's operation can touch them today (shared playlists are P4-10).

## 2. One queued edit: its states

| ID | State | Caused by | What the person sees | Status | Where | Test |
|----|-------|-----------|----------------------|--------|-------|------|
| CF-1 | **pending** | the person edited | the change, at once; nothing says "waiting" | Built | `MutationService`, `outbox` table | `outbox_test.dart`, `encore_mutations_test.dart` (`offline it waits`) |
| CF-2 | **delivering** | the engine took the lease (one engine at a time, renewed before every item; a request has a 30 s timeout) | nothing | Built | `OutboxProcessor` | `db_lease_test.dart`, `engine_concurrency_test.dart` |
| CF-3 | **delivered** | the server answered ok (or "already there") | nothing | Built | | `outbox_test.dart` |
| CF-4 | **waiting to retry** | no network, or the server could not be reached | nothing; the queue stops so order is kept; **offline never counts as a failure** | Built | | `outbox_test.dart` |
| CF-5 | **retrying with backoff** | the server failed the same item (a 5xx) | nothing; waits 20 s, doubling, up to 30 min | Built | `baseBackoff`, `maxBackoff` | `outbox_test.dart` |
| CF-6 | **parked as failed** | the server failed the same item 12 times, or turned it down for good, or its stored data is damaged | "N changes could not be saved" with **Try again / Let go** for each; one parked item **never blocks** the ones behind it | Built | `failed_edits.dart`, `OutboxFailures` | `outbox_failures_test.dart` |
| CF-7 | **dropped as already gone** | the edit is to a playlist the server no longer has (deleted on another device) | **nothing**: the edit is treated as done, and the next pull removes the playlist here too (`17` §5 wants a sentence, "That playlist was deleted on another device") | Built (silent) / Designed (sentence) | `encore_delivery.dart` `gone` | `encore_mutations_test.dart` |
| CF-8 | **lost with the sign-out** | the person signs out with edits still pending | the outbox rows go with the rest of that server's copy (CN-28); **the person is warned first**: "3 changes have not reached your server yet and are lost if you sign out." | **Built** (the warning; the edits are still lost; G-5) | `sign_out.dart`, `ServerSetupService.remove` | `sign_out_test.dart` `the dialog warns about changes that have not reached the server` |

## 3. Two devices of one person, one operation each (the pairs)

"A" and "B" are two phones signed in as the same person; "arrives" is the order in which the server received the operations.

| ID | A does | B does | What the server does | What both phones end up showing | Status | Test |
|----|--------|--------|----------------------|--------------------------------|--------|------|
| CF-10 | like song S | like song S | one like, one change | S liked | Built | `test_liking_twice_is_one_like_and_one_change` |
| CF-11 | like S | unlike S | **the later arrival wins** (the like is a row; unlike deletes it). `17` §5 says the same since G-1 (decided 2026-10-23); only the like carries its own time (to keep the order of Liked Songs) | whichever arrived last | **Built** (arrival order, as `17` §5 says: G-1) | `test_a_like_and_its_removal_arrive_as_the_state_it_is_in_now`, `test_a_like_keeps_the_time_the_person_gave_it_when_that_is_in_the_past` |
| CF-12 | unlike S | unlike S, or S was never liked | not a change | S not liked | Built | `test_unliking_what_was_never_liked_is_not_a_change` |
| CF-13 | add songs to playlist P | add songs to P | both sets are added; the same song may be in a playlist twice | everything from both | Built | `test_two_devices_adds_both_survive`, `test_the_same_song_may_be_in_a_playlist_twice` |
| CF-14 | add after entry E | remove E | E is a tombstone; the add falls back to **the end** | the new songs at the end | Built | `test_an_anchor_that_was_removed_elsewhere_falls_back_to_the_end` |
| CF-15 | add many songs in the same place | add many songs in the same place | positions are fractions; when the gap is too small the playlist is renumbered, order kept | both sets, in arrival order within the gap | Built | `test_many_inserts_in_the_same_gap_renumber_instead_of_losing_order` |
| CF-16 | remove entry E | remove entry E | the second is a no-op; a removed entry stays removed | E gone | Built | `test_removed_entries_stay_removed_and_removing_twice_is_fine` |
| CF-17 | remove E | reorder (a list that includes E) | E is left out of the new order | E gone, the rest in B's order | Built | `test_a_reorder_that_lists_a_removed_entry_leaves_it_out` |
| CF-18 | add entry X | reorder (X not in B's list) | the reorder only permutes the entries it lists, **in the places they occupy now**; X stays where it was added | X kept; B's order for the others | Built | `test_a_reorder_puts_the_listed_entries_in_the_places_they_occupy` |
| CF-19 | reorder | reorder (overlapping lists) | each applies to the entries it lists, later arrival last | the later reorder's order for the entries both list | Built | `library.reorder` | `test_two_reorders_that_overlap_apply_in_the_order_they_arrive` |
| CF-20 | rename P to "X" | rename P to "Y" | **last writer wins by arrival** | "Y" on both | Built | `test_a_rename_is_last_writer_wins` |
| CF-21 | rename, add, remove or reorder in P | delete P | delete wins; later edits of P answer "not found"; the phone drops them silently (CF-7) | P gone on both | Built (silent) | `test_deleting_a_playlist_is_gone_for_the_list_and_not_found_for_edits` |
| CF-22 | delete P | delete P | idempotent: "deleting what is not there is a success" | P gone | Built | same |
| CF-23 | create P (a retry after the network cut) | — | the client-made id makes a retried create **one** playlist; an id that belongs to someone else is a conflict | one P | Built | `test_a_create_that_is_retried_is_one_playlist`, `test_somebody_elses_playlist_id_is_a_conflict` |
| CF-24 | create P with songs, then edit P, all offline | — | delivered in order: create, then the entries, then the edit | P as left | Built | `encore_mutations_test.dart` |
| CF-25 | play report sent, the answer is lost, sent again | — | one play (the report has an id) | one listen | Built | `test_a_report_that_is_sent_twice_is_one_play` |
| CF-26 | add a song the server does not know | n/a | the whole call is refused (`not_found`, with the ref in its details): "A song in that list is not known to this server." | the phone tells the two apart by the error's details (a `ref`, or none): a playlist that is gone drops the edit (CF-7); **an unknown song keeps it as a failed edit** the person can see (CF-6), so nothing is dropped silently | Built | `test_an_unknown_song_refuses_the_whole_call`, `encore_delivery_test.dart` `a song the server does not know, added to a playlist that is there, is a failure that names the song` |

## 4. Other disagreements

| ID | Situation | What happens | Status | Where | Test |
|----|-----------|--------------|--------|-------|------|
| CF-30 | **The server changes a song's file** (renamed, re-tagged, moved, replaced by a better quality) | the song is a **ref**; likes, playlist entries, downloads and history point at the ref, so nothing the person has changes | Built | ADR-R4, `encore_writer.dart` | `encore_sync_test.dart` (`a song whose file is gone stays when a person uses it`), server `test_scanner.py` |
| CF-31 | **The file is gone from the server but a person uses the song** | the row stays; it streams again from YouTube (PB-3) or says it cannot play (PB-8) | Built | `api.py` `stream` | `test_a_kept_song_whose_file_is_gone_streams_from_youtube_again`, `test_a_kept_song_whose_file_is_gone_and_that_youtube_does_not_have_says_it_cannot_play` |
| CF-32 | **A pull while an unlike is waiting in the outbox** | the pull does not bring the like back; the waiting intent wins until it is delivered | Built | `encore_writer.dart` / `pending_intent.dart` | `encore_sync_test.dart` |
| CF-33 | **The same pull twice** | changes nothing and asks only for what is new | Built | `EncoreSync` | `encore_sync_test.dart` (`the same pull twice …`) |
| CF-34 | **A tombstone seen again** (a deleted playlist, a removed entry) | it comes back as deleted; it is not re-created | Built | `EncoreWriter` | server `test_a_deleted_playlist_and_a_removed_entry_are_tombstones` |
| CF-35 | **The cursor is lost or the account is new on this phone** | "reset" makes the next pull read everything again | Built | `EncoreSync.reset` | `encore_sync_test.dart` (`reset makes the next pull read everything again`) |
| CF-36 | **A person edits an imported playlist while the server is still saving its songs** | the import adds its entries once, at creation; the person's later removes are removes (tombstones) and are not undone by the keeper (the keeper saves **files**, it does not edit playlists) | Built (by design; tested as a pair) | `imports/service.py` | `test_an_entry_removed_while_the_songs_are_still_being_saved_is_not_put_back` |
| CF-37 | **"Follow the original"**: the source playlist changed while the person also edited their copy | the person's own additions are never removed; songs the person removed stay removed unless the person says otherwise | **Designed** (P2-17) | none | none |
| CF-38 | **A shared device, two profiles, one outbox** | all profiles share one database; a profile's waiting edits are rows keyed by its server, and only the **active** profile has a session, and so a delivery (the `OutboxProcessor` is made and disposed with the session). **A profile that is switched away from delivers nothing: its edits wait, untouched and without using up an attempt, and go out, in their order, the next time it is active.** The sign-out warning counts per profile, and signing out of one profile takes only its own edits | **Built** (G-5: deliver for the profile that is active) | `profiles/`, `sessionProvider` (disposes the session), `OutboxProcessor` per session | `CF-38: a profile delivers its own waiting edits`, `CF-38: a profile that was switched away from delivers nothing`, `CF-38: when that profile is active again its waiting edits are delivered`, `CF-38: the count of unsent edits`, `CF-38: signing out of one profile takes only its own waiting edits with it` |
| CF-39 | **Two people edit the same playlist** | not possible: a playlist is its owner's; another person's id is "not found"/a conflict | Built; collaborative playlists are **Designed** (P4-10) | `_own_playlist` | `test_nobody_edits_somebody_elses_playlist` |
| CF-40 | **The phone's clock is wrong** | the like's own time (`atMs`) is only used to keep the order of Liked Songs and is ignored when it is in the future; the server decides arrival order; a play report's time is taken as sent | Built | `set_item` | `test_anything_else_is_now` |
| CF-41 | **Playback state written by two devices** | server: a write with an old `rev` gets `conflict` and the current state; **the app never writes it** | Built (server) / **Open (app)** | `playback.py` | `test_api.py` playback tests |

## 5. Gaps and decisions

| ID | Gap | Proposal | Who | Size |
|----|-----|----------|-----|------|
| G-1 | `17` says like/unlike resolve by the latest action time; the server uses arrival order. Which is the rule? | **Keep arrival order** (simple, and a person with two phones online sees the real order within 2.5 s); correct `17` §5, keep `at` for the order of Liked Songs. If wanted later: a tombstone with a time on unlike | **Decided 2026-10-23: arrival order** | S (docs) |
| G-2 | CF-7: a playlist deleted elsewhere vanishes without a word | a one-line notice once: "'<name>' was deleted on another device" | product | S |
| G-3 | CF-19: no test for two overlapping reorders | add it with the pair | **Done 2026-11-01** (`test_two_reorders_that_overlap_apply_in_the_order_they_arrive`) | S |
| G-4 | CF-36: import vs edit has no pair test | add a test: import, remove a song, the keeper finishes: the song stays removed | **Done 2026-11-01** (`test_an_entry_removed_while_the_songs_are_still_being_saved_is_not_put_back`) | S |
| G-6 | CF-26: an add refused for an unknown song looks like "playlist gone" and is dropped without a word | tell them apart by the error's details (a `ref`, versus none); an unknown song parks the edit (CF-6) with its reason | **Decided 2026-10-23: do it; done (2026-11-01)** | S |
| G-5 | CF-8, CF-38: what happens to waiting edits on sign-out and on a profile switch | verify; warn before signing out with waiting edits ("3 changes have not reached the server"); deliver for the profile that is active | engineering + product; **done**: the sign-out warning (CF-8) and the profile switch (CF-38, 2026-11-01) | S |
