# History: what happened, in short (NOT instructions)

Everything here was true on the day it happened. **Nothing here says what to do; where it disagrees with a document of the present, the present wins.** The board (`python tools/roadmap.py brief`) is the state, the decision log (`10`, `11`) is why, `evidence/README.md` is the proof. This file is the one place that explains the old finding IDs that code, tests and documents still cite.

**The long forms are in git, not here.** On 6 Nov 2026 (D-62) the three archive files were shortened to this page. Read an old one with `git show 4f18b3568b:docs/history/reviews-2026-10-31.md` or `git show 4f18b3568b:docs/history/design-reviews.md` (commit `4f18b3568b`, the last `main` that holds them in full). Every section id of the old files is kept below, so `history/README.md#audit` and the others still resolve.

**IDs written like `(docs/23, B8)` in source comments point at a bug checklist of the old project that no longer exists** (the number 23 is now another document). `AUDIT B1` to `B34` are the backend review below. The register `tasks/AUDIT-BUILT-2026-11-05.md` uses `B-1` and up with a hyphen: a different list.

| Record | Date | What it was |
|--------|------|-------------|
| [cloud-resume](#cloud-resume) | 1 Nov 2026 | the work order and progress log of a session that had only the repository |
| [docs-audit-2026-11-01](#docs-audit-2026-11-01) | 31 Oct | 39 contradictions between the documents and the code, and how they closed |
| [qa-backend-2026-10-31](#qa-backend-2026-10-31) | 30 to 31 Oct | the backend review: B1 to B34 |
| [qa-round1-2026-10-31](#qa-round1-2026-10-31) | 31 Oct | QA round 1 (R1-1 to R1-26) and the owner's first field test (F59 to F66) |
| [qa-ui-2026-10-31](#qa-ui-2026-10-31) | 30 to 31 Oct | the three-hour phone walk (Q1 to Q40) |
| [audit](#audit) | 22 Oct to 5 Nov | the owner's findings F1 to F58, D-18, round 2 (R2-F1 to R2-F5) |
| [ux-review](#ux-review) | 30 Oct | the inventory of 266 controls and its findings M1 to M8 |
| [rc-rehearsal-vm107](#rc-rehearsal-vm107), [rc-log](#rc-log) | 30 Oct to 5 Nov | the release-candidate rehearsal plan and its status log |
| [design-01 to 04](#design-01-brief) | 24 to 30 Oct | the design brief, the choice of direction, the owner's review, the screen-by-screen review |

---

<a id="cloud-resume"></a>
## cloud-resume

On 1 Nov 2026 the weekly usage limit ran out and a cloud session (no memory, no emulator) was given a standing work order: merge the server and phone branches in a fixed order, run a documentation coherence pass, add tests for every state row that had none, then stop. **What it did:** merged PRs #84 to #124 (S0 CI hygiene, S1 the public edge, W-05 the join page with B15, S2 silent failures, S3 revocation, the phone batch #91 with 21 commits, the state-table tests until every Built row had one, the Goldens workflow that commits its own pictures). **What it learned and what still holds:**
* **Pictures of the Linux screen tests are drawn only by the Goldens workflow on the branch**, never by `flutter test --update-goldens` anywhere else (the owner's answer); a push by the workflow's token starts no checks, so App is started by hand; `check_rows.py` is run by hand for that commit (`guides/dev-gotchas.md`).
* **An installed server does not update itself from `main`.** Only `encore update` (a backup first, then a pull), a reinstall or a manual pull moves it; the image `:main` moves on a push that touches `server/encore_server/**`, every Monday 04:17 UTC, a `v*` tag or by hand. Only yt-dlp updates itself (ADR-R39).
* **Hard rules of that order that still stand:** never make the repository public, no admin merges, no force pushes to `main`, merge only when every check on the exact head sha is green (`gh pr merge N --squash --match-head-commit <sha>`), at most two agents at a time, never run the cloud and a local machine on the same branches.
* **Decisions D-48 (a to f), advisor, 1 Nov:** tablets are parked everywhere (D-18); the missing decision rows were written; the merge rules point from `AGENTS.md`; notification switches (three built, two in ADR-R44) and minSdk (24 built, 26 decided) are RC2; a wrong server key keeps its own line in the strip; wizard page 6 and D-19/D-20 stay open until the owner decides the public address.
* **Two owner questions were recorded and never asked:** turn the public address (Funnel) on, and scrub the history before the repository goes public (D-49, D-50 hold the answers).
* **Noticed, not fixed then:** a song downloaded on its own that is also in a downloaded release shares one pin row (`33` PB-39); the wrong-key line can show once on a friend's Wi-Fi.

<a id="docs-audit-2026-11-01"></a>
## docs-audit-2026-11-01

Two read-only agents compared 80 markdown files with the code on 31 Oct and found 39 contradictions in two slices. The classes: **backups** described as VACUUM INTO and a 7+4-week schedule while the code uses SQLite's online backup (ADR-R37); **numbers** (signed addresses 5 min vs 6 h, sign-in limit 5/min per person vs per name, audio profiles Opus 64/192 vs 48/160, backup time 03:00 vs 03:30, disk minimum 20 GB vs 6 GB); **state rows** describing a strip that no longer existed (D-45) or citing tests that did not exist; **revocation rows** that overstated the server before S1/S3; **gaps shown open that the code had closed**; **decisions living outside the log** (D-21, D-22, D-45 to D-47); **names** (the Tailscale sidecar replaced by the machine's own Tailscale, ADR-R25; the layout `06` named and nobody made); **CI** described in `06` that did not exist; **ID spaces** that overlapped (`D-5` as an owner decision and as a gap id; `ADR-011`, `R-09` and `R-19` in `16` were never defined; `07` said "S1 to S4" and only S1 to S3 exist; the README said "ADR-R1...R14" while the log reached R1-R44). All were fixed in PRs #92 to #124 except four lines marked OPEN in the documents concerned (wizard page 6, D-19/D-20, the documentation rules of `06` section 6, the search-timing target N7). **The method is the lesson:** read the document, find the file and line in the code, say which is right; a state row says Built only when a test names it (`tools/check_rows.py`). The 6 Nov 2026 audit (`tasks/AUDIT-BUILT-2026-11-05.md`) repeated it by running instead of reading.

<a id="qa-backend-2026-10-31"></a>
## qa-backend-2026-10-31

A testing agent ran the server's suite (640 tests, 91.5 % coverage), reviewed the server against `17` and wrote 18 proof tests. **Verdict: the privacy between people, the invitations, the tokens, the signed addresses, the SQL, the paths and the migrations were sound; the defects were at the edge that faces the internet and in revocation.** D-41 added a sixth category to D-29's cut-line: a hole a stranger can use from the internet, or one member against another's data. The advisor's corrections: failures only throttle, never lock (B2); a limiter never refuses a correct login because of others' failures and is keyed on (name, address) plus a cap per address (B1); the right-most untrusted `X-Forwarded-For` entry counts (B11, a prerequisite of B1); read the outbox before changing B3.

| ID | Finding | State |
|----|---------|-------|
| B1 | passwords could be guessed without limit on every route but `/auth/login` | fixed, S1 (#86) |
| B2 | a stranger could lock the only owner out with 20 wrong passwords | fixed, S1: failures throttle, the lock is the owner's alone |
| B3 | a song added to a deleted playlist was dropped without a word | fixed in the phone batch: only a not-found that names a song is kept as a failed edit; a deleted playlist wins |
| B4 | a removed person worked for 10 more minutes and came back as new | fixed, S3 (#89) |
| B5 | a signed-out device kept receiving live updates | fixed, S3: the socket closes with 4401 |
| B6 | whoever first described a song decided its audio and picture; any https picture was loaded | picture allow-list fixed (S3); the audio part is later |
| B7 | a keep whose file was never found retried every 30 s for ever | fixed, S2 (#87) |
| B8 | while YouTube rested, every tap still searched and was not counted | fixed, S2: a tap during a rest makes no search |
| B9 | no limit on request size | fixed, S1 (4 MiB own API, 1 MiB passed on) |
| B10 | fair share breaks past 200 queued items | later; proven again 6 Nov (register B-39) |
| B11 | limits trusted an address the client writes | fixed, S1 (`netaddr`) |
| B12 | the music server's web page, `/api`, `/auth` and `/rest` were public through Funnel | blocked paths fixed (S1); B12b: `/rest` had no guess limit, fixed 3 Nov |
| B13 | signed addresses (6 h) and picture passes (7 d) outlived a lock or removal | fixed, S3 |
| B14 | one import kept the home line at YouTube for a day and a half | later (budget) |
| B15 | a join was not safe to repeat when the answer was lost | fixed, W-05 (#88) |
| B16 to B24 | raw error text reaches the phone (B16); the container can write the whole library (B17); backups may reveal friends' passwords, no `ND_PASSWORDENCRYPTIONKEY` (B18, still open: register B-27); `/openapi.json` public (B19, fixed S1); migration backups never pruned (B20); a job that crashes the server retried at every start (B21); live channel without limits (B22); a partial playback write clears the song (B23); a stranger's import id is a 500 (B24) | later |
| B25 to B29 | the image built on every push (B25, fixed S0); unpinned dependencies (B26); 17 tests call Deezer (B27, fixed S0); the flaky account-model test (B28, fixed S0); deploy-script tests pick WSL bash (B29) | S0 |
| B30 to B34 | lists cut off silently (B30); unbounded data (B31); leftover files after a crash (B32); the installer opens the port to every interface (B33); the keeper retries a slow YouTube answer for ever (B34, parked `rc2/B34-timeout-retries`) | later |

<a id="qa-round1-2026-10-31"></a>
## qa-round1-2026-10-31

Round 1 (build 123, two emulators, the integration build of every server branch) found 26 things (7 defects, 11 confusing, 8 wishes). Passed as written: Q1, Q2, Q30, F40, D-26, D-32, sign-in and out, playlists, downloads, offline play, Now playing. **The owner then used a phone outside for the first time** and found what no emulator had: the states people live in (4G on with no data, a public Wi-Fi sign-in page). **The rule that came out of it: offline is not airplane mode.**

| ID | What | State |
|----|------|-------|
| R1-1 | the owner had no Invite someone and no People: the first "who am I" ask went to an unproven address and was never repeated | blocking, fixed |
| R1-2 | "Play any song" kept saying "did not answer" after the server returned | fixed |
| R1-3 | an instrumental showed "Artist / Album / Title" as its lyrics | fixed |
| R1-4, R1-5 | landscape: mini player under the system buttons, a full-screen cover | D-47: phones stay upright |
| R1-6 | light theme: dark-grey text on a dark olive mini player | fixed 31 Oct |
| R1-7 | 200 % text: Home tiles cut their names | RC2 |
| R1-8 | the words "Cannot reach the server" for a reachable server | went with R1-1 |
| R1-9 | offline, the address row has no state | RC2 |
| R1-10 | "Songs it already has still play" shown offline | fixed, said once on the page |
| R1-11 | the song menu offers "Remove download" on a song that stays because a downloaded release has it | RC2: say why before the tap |
| R1-12 | Download on an empty playlist also switches on automatic download | wording, RC2 |
| R1-13 | after deleting a downloaded playlist "12 songs on this phone", 10 listed | fixed with F59 |
| R1-14 | nothing tells a kept song from a catalogue one | closed by design |
| R1-15 | offline, covers of albums that are not downloaded turn into letters | RC2 (the cover cache) |
| R1-16 | the offline banner covers the last rows | mostly gone: the strip shows 5 s |
| R1-17 | Welcome with the keyboard open: Connect is off screen | RC2 |
| R1-18 | mechanical overlaps with the navigation bar | none that matter |
| R1-19 to R1-26 | wishes: the address hint says 4533, sign-out forgets the address, Like has no confirmation, sheets do not dim the mini player, no Like or Shuffle in the notification (F58), black covers vanish on true black, the "Downloaded" chip is clipped, "Downloading X" when it is already there | the owner's list or RC2 |
| F59 | a deleted downloaded playlist still said "x songs downloaded" | fixed: a removed pin takes its songs at once; PB-39 and PB-40 in `33` |
| F60 | one missing song stopped a playlist (4G on, no data) | fixed, D-46: "can reach the server" is a network and a server not known to be out; Play and Shuffle start at a downloaded song |
| F61 | "never says offline, always fails to connect" | fixed, D-45: one calm strip, once per outage |
| F62 | after public Wi-Fi the app opened on the page that asks for a server | open, cause unknown; hardened |
| F63 | the previous title and cover stay under the next song | open, not reproduced |
| F64, F65, F66 | a volume slider (the app has none), which songs of a playlist are downloaded, which test machines | answered or a wish |

**Decisions (advisor, reversible):** D-45 the calm strip; D-46 what "can reach the server" means for the player; D-47 phones stay upright.

<a id="qa-ui-2026-10-31"></a>
## qa-ui-2026-10-31

The owner's private page with the clips, the pictures and the backend review is (a private claude.ai artifact, not public) (157 pictures and 4 clips in the agent's own report, which is not in the repository). A testing agent drove the app for about three hours (112 steps, build 122, no crash, no warning in the log). Everything seen was on the dev VM's old stack beside the new, so nothing counted as a pass. **RC1 candidates (D-42):** Q1 the download arrow on an empty playlist stays at 0 % for ever; Q2 Play and Shuffle on an empty playlist do nothing; Q30 offline, a refused tap changed the player and queue and started later; Q12 "41 songs on this phone" while nothing is stored; Q31 airplane mode left Your server green. **Q3** an album plays A to Z because imported songs carry no track number: the data is the cause, moved to RC2 (the fix needs a catalogue pass of its own). **Later:** Q4 swipe down does not close the player; **to answer on the release-candidate pair, not on an emulator: Q6, Q10, Q11 (a "Can't reach your server" banner while everything worked), Q19, Q28, Q38, Q39, Q40; Q5 and Q27 no visible remove or Undo for queue and playlist rows; Q7 the sleep timer shows nothing while running; Q9 the Albums chip shows new releases; Q14 jargon; Q15 an equalizer preset silently turns it on; Q17 search mixes your music and the web; Q18 some pages hide the mini player; Q20, Q21 letter tiles and toasts without names; Q25 sort options; Q32 Back from a tab leaves the app; Q34 a double tap opens a page twice; Q35 and Q36 200 % text and landscape; Q37 settings search matches page names only**. Decided or built before the report: Q8, Q29, Q16, Q24, Q23, Q33, Q26, Q13. **What worked and must not break:** tap-to-play, the heart, seek, synced lyrics, queue drag, the sleep timer, media keys, the queue surviving a force-stop, true black disabled in Light with its reason.

<a id="audit"></a>
## audit

The owner's findings from 22 Oct to 3 Nov 2026 with their causes and where each went, plus per-phase status lines of 3 to 5 Nov that the board replaced (frozen 6 Nov; D-60 makes the board the tracker). **The F-numbers below are the IDs that code and tests cite.**

| ID | Finding | Where it went |
|----|---------|---------------|
| F1 | a tap played a 30-second preview: one failed look for the instant-play service was remembered for the session | fixed |
| F2 | an imported playlist showed letters, not a picture | fixed on an Encore server (source picture, then a collage) |
| F3 | no download button on an imported playlist | fixed; "Waiting for Wi-Fi" wording |
| F4 | Downloaded was one heap of songs | fixed: playlists, albums and Liked Songs with progress |
| F5 | "Only my music" should be the default | fixed ("Show the whole server") |
| F6 | shared devices need user switching | first slice built (Who's listening); PIN, Guest, TV focus open in P4-16 |
| F7 | two phones, one account: an import must appear on both | proved 2.4 to 2.6 s through the live connection (`evidence` b01) |
| F8 | test like a new user, end to end | the closing journeys |
| F9 | no lyrics for one song | not a bug: the lyrics catalogue lacked it |
| F10 | the Devices dialog is Android's own switcher | Encore's own Devices sheet is P4-07 |
| F11 | an artist page mixed songs and albums | built: Popular, Albums, Singles and EPs, Compilations |
| F12, F13 | a day-old release is absent and search misses it; a song with two artists shows one | cause: the catalogue was Deezer only and its `contributors` were ignored; fix is P2-12 (YouTube Music as a first-class source, all credited artists) |
| F14 | the install was all terminal | the browser wizard is drawn, not built (P3-06) |
| F15 | no choice of source (YouTube or Soulseek) | D-19: a "Where songs come from" step |
| F16 | the QR code opened Navidrome | the installer prints no QR; the pairing link is P2-19 B |
| F17 | Tailscale never explained | the wizard's step; the installer's last screen |
| F18 | a GitHub login was needed (private image) | ends when the image is public (P5-06); today register B-1 |
| F19 | no YouTube sign-in step | D-20: none in v1 |
| F20 | the new server has no admin pages | P3-06, PC only |
| F21 | Download said "downloaded" at once and kept nothing | fixed #43: both buttons became server operations (D-21) |
| F22 | lyrics "not working": a miss was remembered a day | shorter memory and "Try again"; lookups move to the server (P2-14) |
| F23 | an empty server's first run | a designed path in P3-06 |
| F24 | the server address was typed by hand | P2-19 B and C |
| F25 | an empty Popular list showed as a network error | fixed #44 |
| F26 | sign-out warned about a refused play mark | fixed #44 |
| F27 | retracted: an unliked song is not a missing like | none |
| F28 | a 3 GiB VM shows 93.6 % used | the page cache; the guide states 2 GB and 6 GB free |
| F29 | the first download asked for notifications, against ADR-R44 | removed; D-52 later allows one ask at the first Download |
| F30 | a fresh sign-in stays in the old mode for about two minutes | shortened; first-run stopwatch in the rehearsal |
| F31, F32 | no long-press or menu on Library rows; no multi-select | D-26 wired the menus; P2-21 |
| F33 | a tap played a silent 30-second snippet | fixed #52: never silent (D-24) |
| F34 | "0.1.0" says nothing | About shows build and commit (#57) |
| F35 | the player showed Private and speed every time | removed (D-23) |
| F36 | Bluetooth after switching output | needs a real phone |
| F37, F44 | many half-implemented controls; question every screen | the UX review and the controls audit (J12) |
| F38, F52 | a hint looks like typed text; helper text as bright as a label | hint style fixed (#57); helper style later |
| F39, F40 | inviting without an away address ends in red; "Check addresses" looks broken | plain words; per-address state |
| F41, F42 | the scope switch in two places; true black in light mode | one place (D-27); disabled with a reason |
| F43 | no "add friend" or "edit profile" | D-27; friend surfaces hidden where absent |
| F45 | the output chooser moved the whole phone's sound | the icon removed (D-28) |
| F46, F48 | the app looks nothing like the design; the installer UI is drawn not built | D-43: the built screen is the reference |
| F47 | the sign-in has no album wall | D-31, D-38: real covers only on a valid invitation, RC2 |
| F49 | downloading a whole album for one song | per-song Download (D-32) |
| F50 | Home's Jam chip is a dead end | hidden where the server has no Jam (D-33, #59) |
| F51 | the avatar and the gear open the same page | the drawer (D-34, #60) |
| F53 | Diagnostics cannot say Encore or old mode | a `session:` line added |
| F54, F55, F56 | a raw sync timestamp; a lone "Save" in the queue; the "Downloaded" chip off the edge | later (F54 seen again 6 Nov: register B-52) |
| F57 | "Share what I'm listening to" did nothing on an Encore server | hidden by capability (D-37) |
| F58 | the media notification has empty side slots | a Like and a Shuffle later |
| D-18 | only the phone and the PC are designed and built | TV, tablet, phone admin and web player parked |
| R2-F1 | error text stays under a corrected address | later |
| R2-F2 | a download shows no progress or notification | P2-22; D-52 asks once |
| R2-F3 | "[Unknown Album]" cards | display rule built (#136); cause P2-12 |
| R2-F4, R2-F5 | a new member sees the shared shelf at once; no offline sign on Home and Library | said in the friend guide; P1-15 built |

**Also in this record, kept as facts:** the thin-client debts (the phone still called Deezer and LRCLIB itself: ADR-R38's table); **security S2** (the address probe sent the login token to every candidate address: fixed by ADR-R40 slice A, a server key as identity); the findings of 23 Oct from writing the state tables (sign-out did not revoke the device, the token travelled in the URL, a server that does not answer was treated as a bad song, an expired signed address was not checked on the one quiet retry, an unknown-song add was dropped silently, arrival order decides like against unlike); **yt-dlp freshness** (a weekly image rebuild, then a daily PyPI check with a canary that switches at the next quiet start: ADR-R39); the installer proofs (5.5 to 6 minutes on a clean VM, 14 min 25 s by the owner, backups, an install that survives a closed terminal: `evidence` c01 to c04); the pacing proof (a 217-song import fetched in about 46 minutes, 223 look-ups, no refusal); **round 2 on 3 Nov** (build 125, J10 passed in 5.3 s). The closing journeys (a fresh server, a fresh app with an import, a friend joins, two phones, a Jam, a Jam across servers, a shared tablet, updates and restore) are now the gates of the board.

<a id="ux-review"></a>
## ux-review

An inventory of 266 controls in 16 feature folders, generated from the code on 30 Oct by `tools/ux_inventory.py` (run it again for a current one), with eight questions asked of each. Its mechanical findings, cited by code and decisions: **M1** three import screens (one per kind of server; an Encore server shows one); **M2** two invitation flows (one on an Encore server); **M3** the old request portal still in the product (hidden where there is instant play; the code is P2-07); **M4** "Play songs your server does not have" in two places; **M5** "Ask for better quality" is a portal action (hidden on Encore); **M6** `your_server_screen.dart` mixes the old setup with Encore; **M7** 42 controls had no handler in the scan (mostly false positives; check by tapping); **M8** true black in light mode (F42), the scope switch twice (F41), no friend or profile screen (F43).

<a id="rc-rehearsal-vm107"></a>
## rc-rehearsal-vm107

The plan to rehearse the first install on VM 107 (the owner's own, rolled back to a clean snapshot, at most 10 YouTube look-ups, journeys J1 to J13 on a fresh emulator install). VM 107 was destroyed on 3 Nov at the owner's word; the clean-machine install was done on VM 108 by the guide (`evidence` c06). The journeys: **J1** first run with a stopwatch; **J2** search an artist, download a single and a release, then offline; **J3** Add to library on its own; **J4** kill the app mid-download; **J5** stop the server mid-song and at a tap; **J6** a tiny import, then the bell; **J7** lyrics, also for a song that appeared later; **J8** sign out (the dialog counts only edits); **J9** the first download raises no permission dialog; **J10** a friend joins by invitation from a second emulator; **J11** install by the guide; **J12** the controls audit; **J13** a cold start, then a tap: the full song.

<a id="rc-log"></a>
## rc-log

The release-candidate status log, 30 Oct to 5 Nov. The sequence: B0 and B1 (#47) closed; decisions D-23 to D-47 (player menu, no silent snippet, the build identifies itself, menus wired, the cut-line D-29, the design verdict D-43, the Actions-minutes cut D-44, the calm strip D-45); F33, the RC1 batch A (F34, F35, F38, F42, D-28), the Jam chip and the avatar drawer (#59, #60), B2 (the downloaded release is one entry, #62 and #63); the backend review and the phone walk; **pushes paused until the Actions minutes reset on 1 Nov (2,711 of 3,000 used)**; everything built locally and tested, then pushed in order (S0, #63, S1, W-05, the phone batch, S2, S3); round 1 and the owner's field test; **3 Nov: the pair is built (app build 125 at `fad1b45`, server image `:main`), the install test passed on a bare VM (9 min 51 s), Funnel ran once for real, round 2 started**; **5 Nov: CI upkeep P0-11 (Node 24 actions, `ubuntu-26.04`, Dependabot) republished the image; the Android toolchain moved (Gradle 9.3.1, AGP 9.1.0, Kotlin 2.4.0) so build 125 predates it; build number 126 is taken by a smoke-test APK, the next candidate takes 127.** After this the board is the status.

<a id="design-01-brief"></a>
## design-01-brief

The page the owner is shown, "Encore Design Choice" ((a private claude.ai artifact, not public)), has its source in `design/directions/index.html`. 24 Oct: the owner asked for every page drawn before it is coded, "with multiple versions". The brief asked three directions to draw four anchor screens (Home, Now playing with the mini player, Search with an Artist page, Welcome with Your server) at three layout classes, with honest states, real data, tokens not colours, 200 % text, right-to-left, 48 px targets and contrast pairs. **A** cover-led, **B** quiet editorial, **C** warm home.

<a id="design-02-direction-choice"></a>
## design-02-direction-choice

**ADR-R43; closed by the owner on 24 Oct: only the cover-led direction A continues, in Spotify-like colours and layout.** From B it keeps the state marks (waiting is an amber dashed scrubber and a hollow thumb, cannot play is red hatched at 0:00 with a retry, offline is grey plus the words "Not downloaded"; colour is never the only cue) and the 200 % and right-to-left rules; from C the friendly first-run personality, on Welcome, Join, Sign in, Your server and the invitation screens only, never on Home or the player. **Three tabs** (Home, Search, Your Library); one thin strip everywhere for "the server does not answer". Found on the way: the light theme failed contrast (accent 3.1:1); fixed since (`tokens.dart` uses `#07703F`, `#BC2318`, `#A63F06`).

<a id="design-03-owner-review-2026-10-24"></a>
## design-03-owner-review-2026-10-24

The owner's ten points and their verdicts. **The rule that came out of it: familiar screens copy Spotify's arrangement exactly and are not "improved"; personality belongs on the welcome and first-run screens; nothing on screen shows what the listener does not need to know.** Three tabs confirmed; people on the same server are already there and anybody else arrives by an invitation link or QR; a shared server is named for the household ("Our music"), never for a person; **the UI follows the server's capabilities** (anything that crosses servers shows only when `GET /info` `features` says it is on, with no placeholder or greyed menu); Your server drops the "Check addresses" button; the listener never sees "owned or catalogue" (only the downloaded arrow, the heart, the E, and offline "Not downloaded"); a **taste comparison** is recorded for later (US-65, P4-17, opt-in on both sides, either can withdraw at once); Now playing copies Spotify's mobile arrangement. Later rounds, decided by the advisor while the owner was away: Smart Shuffle and a recommended-song sparkle wait for P4-01; **no phone notifications by default** (ADR-R44; the in-app bell is the channel); a page for "your account"; the server's browser pages were drawn too (the admin rail of eight: Home, People, Library, Away from home, Backups, Updates, Settings, Logs); the code wins on conflicts (password minimum 8, a six-digit Quick Connect code, Opus 96).

<a id="design-04-review-2026-10-30"></a>
## design-04-review-2026-10-30

A review of every drawn screen (62 screens, 299 states, 654 frames in five files) against what was built on 30 Oct: what exists, what differs, what is missing, eleven pages never drawn, and the find that **W-05, the page an invitation link opens, was a dead end** (built since: #88). **D-43 (31 Oct) voided its "frame is stale" and "redraw" proposals: the built screen is the reference wherever a screen exists, and a page is drawn only when it is new and about to be built.** The eight criteria every screen is judged against still stand and are kept in `design/00-screen-inventory.md`: every reachable state drawn; familiar; plain words; honest (no control that promises what the server cannot do); works at 200 % text, both themes, 48 dp targets and screen readers; phone and PC only (D-18); a joining friend's path judged on its own; a screen shows only what this server can do, decided by a capability and never by guessing the mode.
