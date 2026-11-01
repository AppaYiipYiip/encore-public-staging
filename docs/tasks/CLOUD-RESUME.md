# Resume from the repository alone (written 2026-11-01, the day the weekly usage limit ran out)

For a session that starts with **only this repository** (Claude Code on the web, or a new PC): it has none of the earlier session's memory. Read `AGENTS.md`, `docs/README.md`, then this file, then the last log entry (22) of `RELEASE-CANDIDATE.md`. The owner is not a tester and is not asked to test; he is asked only what only he can decide (section 6).

**Status 2026-11-01, evening:** everything in the table of section 2 is merged, except the parked `rc2/*` branches, `integration/qa-round-1` and the `docs/coherence-pass-1` draft (its claims were re-checked and used for `docs/22`). Sections 2 and 3 are the history of that push; **Progress below is the current state**. What only a local machine can do is the second paragraph of section 4 and the owner's two questions (section 6).

## Work order

Given by the owner on 2026-11-01 after the section 0 report, copied word for word. It replaces the "stop and wait" of section 0 and the merge order of section 3 (the phone batch is now merged last). Progress, below it, is the channel to the next local session and to the owner.

STANDING WORK ORDER (you can work from this for a long while without asking me anything; if you are unsure, choose the safer option and record it in Progress). STEP 0, FIRST: in your first docs PR copy this whole order into docs/tasks/CLOUD-RESUME.md as a section "Work order" with an empty section "Progress" under it; after every merge and at the end of every phase update Progress (on main, through a small docs PR; you may batch these) with PR numbers, merge shas, the head sha of any branch you pushed, and what is blocked and why: Progress on main is the channel to the next local session and to the owner, not this chat, and it survives your context being compacted.

PHASE 1, MERGES in this order: S0, #63, S1, W05, S2, S3, then the phone batch last (S2 and S3 are server-only and must not wait for a goldens or Flutter problem); follow CLOUD-RESUME section 3 for commands; merge only after every check run on that exact head sha is green, via gh api PUT pulls/N/merge with merge_method=squash and sha=<full head sha>, area-prefixed title, then read main's own run. The S0 PR (84) is all green now: merge it first, and check whether your encore-fetch test fix already covers the flaky legacy test (test_stops_looking_when_the_service_has_stopped) before doing anything else about it. For the server branches: pip install the server dependencies and run ruff, mypy and pytest --ignore=tests/integration in server/encore_server before pushing any rebased branch; resolve purely mechanical rebase conflicts (imports, adjacent lines, docs) yourself and rerun the suite; stop on a conflict only where choosing a side changes behaviour. For the phone batch CI decides: if anything other than the two Linux goldens (library_list, now_playing_waiting) goes red, install Flutter 3.47.7 in the session and work the failure locally before pushing again; if the redrawn goldens cannot be delivered, leave the PR open with everything else green, write it in Progress and move on.

PHASE 2, DOCS COHERENCE PASS from docs/tasks/DOCS-AUDIT-2026-11-01.md: small PRs, one family of files each, run python -I tools/check_rows.py --max-missing 61 before each, flip a "Decided ... not on main yet" row to Built only once its test is on main (after the phone batch merges), reuse the docs/22 draft on backup/docs/coherence-pass-1 only after checking it against ADR-R37 and the code, and for a real product choice write an "OPEN (needs owner/advisor)" line in the doc and in Progress and do not decide it.

PHASE 3, TESTS for state-table rows that have none: server rows first (pytest runs here), then app rows with Flutter installed locally, batched into few PRs so Actions minutes are not spent one PR at a time; whenever the untested count drops, lower --max-missing in docs.yml in the same PR.

PHASE 4, the small code-review leftovers, test first: the released map in the download providers keeps one release per song, the track menu says Removed for a song that is still wanted by another pin, and nothing else; then stop. Do not touch rc2/*, integration/* or any RC2 feature.

HARD RULES: never make the repository public, never admin-merge, never force-push main, never delete branches, no tags or releases (read the server-image.yml triggers first: a tag may publish an image), no workflow edits except to repair a broken one, no pushes to branch names matching task/**, no secrets, no billing, keep total GitHub Actions use this week under about 1,200 minutes including the merges, at most two agents at a time.

WHEN BLOCKED: write it in Progress and go on to the next independent item; stop completely only for a red main you cannot fix at once, a security question, or credits about to run out. The two owner questions (turning the public address on after S1, and scrubbing the history before publishing) go only into Progress, never ask them. Post two lines in this chat at the end of each phase.

### Goldens, alone (added 2026-11-01 at the owner's request; the one workflow edit the HARD RULES allow)

When App is red only on screen pictures after a screen changed on purpose, a cloud session does the pictures itself. The artifact host is blocked from the cloud, and the owner's answer is that the workflow's pictures are the only source: **never `flutter test --update-goldens` anywhere else**.

1. Start the workflow on the pull request's branch (never `main`): `gh api -X POST repos/AppaYiipYiip/encore/actions/workflows/goldens.yml/dispatches -f ref=<branch>`; wait for the run to finish (about 10 minutes).
2. It commits only the changed `app/test/features/goldens/linux/*.png` to that branch, with a message that names the run, and uploads them as the artifact `goldens-linux`. `git fetch origin <branch>` and look at the pictures (the Read tool shows PNGs): they must show what the screen should look like.
3. A push made with the workflow's own token starts no checks. Start App on the new head by hand: `gh api -X POST repos/AppaYiipYiip/encore/actions/workflows/app.yml/dispatches -f ref=<branch>`, and wait for its `verify` job (a `workflow_dispatch` run, so it also builds the debug APK). Do not push an empty commit and do not close and reopen the pull request.
4. Merge when every check run on that exact head is green, with the sha guard, and read `main`'s own run. Hygiene does not run for the workflow's commit: run `python -I tools/check_rows.py --max-missing <the number in docs.yml>` yourself.
5. If the branch moved after the run started, the push is refused: fetch, rebase, run the workflow again. Details and the reasons: `docs/guides/dev-gotchas.md` and the comments in `.github/workflows/goldens.yml`.

## Progress

<!-- One entry per merge and per phase, newest last: PR number, merge sha, the head sha of any branch pushed, and what is blocked and why. -->

### Phase 1, merges (2026-11-01)

Every PR below was squash-merged with `gh api PUT pulls/N/merge` and `sha=<head>` after every check run on that exact head was green. The rebased server branches were checked locally first (`ruff check`, `ruff format --check`, `mypy encore_server`, `pytest --ignore=tests/integration` in `server/encore_server`, all clean) and were pushed only to the session branch `claude/zealous-maxwell-7s5nio`; no `task/**` branch was pushed.

| # | PR | Merge sha on main | Head that was merged | What | main's own run |
|---|----|-------------------|----------------------|------|----------------|
| 1 | #84 | `8b7cb8a` | `b92d6bb` on `backup/task/S0-ci-hygiene` (the S0 commits plus one of mine) | S0: CI cuts (D-44), the server image only after tests on main and `v*` tags (B25), B27, B28 | Server, Server legacy, Hygiene and Server image green (first real run of the `tests` and `image` jobs); App `verify` green, its Android build cancelled by the next merge's push |
| 2 | #85 | `c42d411` | `72d7f18` on the session branch | this work order | Hygiene green |
| 3 | #63 | `513d875` | `2c924ec` on `task/B2-one-entry-per-release` | B2 second half: a downloaded release is one entry | Hygiene, App `verify` and the Android build all green (the first Android build on main under the D-44 `if`) |
| 4 | #86 | `9aba607` | `2e2b823` on `backup/task/S1-public-edge` | S1: the public edge (B1, B2, B9, B11, B12, B19) | Server, Hygiene and Server image green |
| 5 | #88 | `b90435b` | `2a1995f` on the session branch (W05 rebased with `git rebase --onto origin/main 2e2b823`) | W-05 join page (D-39), B15 | Hygiene green; its Server runs were cancelled by the next push, whose run covers it |
| 6 | #87 | `9ba6dd4` | `749d423` on `backup/task/S2-silent-failures` | S2: B8 (no search while YouTube rests, every search counted), B7 (a never-found file ends as a failed keep) | Server, Hygiene and Server image green |
| 7 | #89 | `4b9d957` | `f728c61` on the session branch (S3 rebased with `--onto origin/main 309ebbd`) | S3: B4, B5, B13, B6 (revocation) | Server, Hygiene and Server image green |
| 8 | #91 | `451d4dc` | `9db25db` on the session branch (`30a6b0c` plus the goldens commit of the local side) | the phone batch: 21 commits, 84 files (see below) | Hygiene green; App: `verify` and the Android build green (run 41321073812) |

What else happened, for the next session:

* S0's first real run showed one red: `test_stops_looking_when_the_service_has_stopped` in `server/legacy/encore-fetch` (the same assertion had failed on main on 2026-10-25, run 40153063719). Cause: the fake service lived 2 s and the update loop looks every 1 s, so the loop's second look fell exactly when the service ended. Fixed on S0's branch (commit `b92d6bb`, only the timing of the test: the service lives 3 s, the loop looks every 2 s; the assertion is unchanged). Checked: 2 of 20 runs failed before, 0 of 20 after, and the test still fails (`7 != 4`) when the loop's `kill -0` guard is removed from `entrypoint.sh`. Someone also re-ran the first attempt of the legacy workflow on GitHub; that does not remove the cause.
* On main before S0, `pytest` could fail in `test_account_model.py` when Hypothesis found a lock followed by an unlock (the model said the device works again, the server correctly kept it dead). That is B28, fixed by S0.
* The B25 change works: pushing to main ran `tests` and then `image` and published the image to the private registry; a task branch no longer builds one.
* #63 was merged as soon as S0's `verify` job on main was green. Its push cancelled S0's Android build through the workflow's own `cancel-in-progress`; #63's run builds the APK on the combined tree.
* `tools/check_rows.py` reported 60 Built rows with no test on main at `4b9d957`; Phase 3 brought that to 0 (see the entry below).
* GitHub Actions used since 2026-11-01: about 187 minutes over 41 runs at 13:46 UTC (job durations rounded up to whole minutes; runs still going are not counted).
* Decisions taken without asking: every rebased branch went through the session branch and no other branch was created; the session branch is reset to `origin/main` and force-pushed with a lease after each merge (it holds no work that is not on main).

OWNER QUESTIONS (recorded here only, not asked):

1. Turn the public address (Funnel) on? S1 (B1, B2, B9, B11, B12, B19) and S3 (B4, B5, B13, B6) are merged, but two things stay open: whether the Funnel really sets `X-Forwarded-For` as B11 assumes (only checkable on the owner's Funnel), and narrowing `/rest`; the app also still sends the old login, not the Bearer token. Turning it on exposes the owner's server to the internet. `docs/guides/install-test.md` step 5 tells a person to run `encore funnel on` without this warning.
2. Scrub the history and publish the repository? It is not needed (the Actions minutes reset); it cannot be undone; the history holds the owner's tailnet name, first name, real artist names in the design drawings and machine names.

### Phase 1 end, and Phases 2 to 4 (2026-11-01, evening)

**Phase 1 is complete: the phone batch, PR #91, is merged** (squash `451d4dc`, head `9db25db` on the session branch `claude/zealous-maxwell-7s5nio`; 21 commits: the 20 of `task/RC1-app-batch` rebased with `git rebase --onto origin/main 2c924ec`, plus the goldens commit). On its first head (`30a6b0c`) App `verify` was red only on the two expected Linux goldens, `library_list` and `now_playing_waiting` (2,135 tests passed, 2 failed). This session could not fetch the artifact (the proxy denies `productionresultssa18.blob.core.windows.net`), so the local side downloaded the artifact `goldens-linux` of Goldens run 41313093095 (drawn on `30a6b0c`), found the 12 other pictures byte-identical, looked at the two that changed, and committed them as `9db25db` on the origin branch `goldens/redraw-pr91` (left as it is). The session branch was fast-forwarded to it; App `verify` and Hygiene were green on that exact head before the squash. main's own run on `451d4dc`: App `verify` and `android-debug-build` both green (run 41321073812), Hygiene green (run 41321073840).

**The owner's answer to the OPEN question of the earlier entry:** the workflow's pictures are the only source. **Never draw the Linux goldens with `flutter test --update-goldens` on any other machine**, even one that renders the same (this one did, to the pixel: 2,100 and 1,025,972 pixels).

**Goldens, alone (PR #110, merge `8f95e86`).** `goldens.yml` now commits the changed `app/test/features/goldens/linux/*.png` (and nothing else, never on `main`) back to the branch it ran on, as `github-actions[bot]`, and still uploads the artifact. The procedure is the numbered list "Goldens, alone" in the Work order above. The loop was run once end to end on a throwaway branch: Goldens run 41319484509 committed only `library_list.png` (`c46d0c9`); App was then started by hand with `workflow_dispatch` (a push by the workflow's token starts no checks); the first App run stopped at `Format` on one line of my throwaway test edit (run 41319936423); after a format fix, App run 41320286021 on `23f2825` was green in `verify` (the bot's picture compared at zero tolerance) and in `android-debug-build` (the debug APK builds, as a `workflow_dispatch` run does). The throwaway branch `ci/goldens-loop-test` (head `23f2825`) is **never to be merged**; it stays on origin as the record (nothing is deleted).

**Merged since the table above** (each from its own branch, none deleted, none under `task/**`; head sha, then merge sha on `main`):

| PR | Branch | Head | Merge | What |
|----|--------|------|-------|------|
| #92 | `docs/ops-backups-and-pacing` | `acb4fc9` | `91a43f9` | docs 22, 04, 10, 26, P1-03: backups, updates, canary, pacing (from the unfinished docs/22 draft, every claim re-checked against `deploy/encore`, `backup.py`, `canary.py`, `pace.py`) |
| #93 | `docs/revocation-rows` | `bf86815` | `9df7fee` | docs 32, 31, 17: revocation rows say what S1 and S3 built |
| #94 | `docs/entry-points` | `3414190` | `5abfd2d` | AGENTS, README, docs/README |
| #95 | `docs/numbers-audio-and-install` | `0234a0c` | `d0600a4` | docs 23, P3-05: audio numbers, the installer's disk minimum |
| #96 | `docs/tailscale-is-not-a-container` | `f3e3ed6` | `60c30dc` | docs 04, 15, 03a, 25: away from home is the computer's own Tailscale |
| #97 | `docs/progress-phase1-end` | `4c7ad1a` | `8d8c333` | this Progress, phase 1 end |
| #98 | `docs/api-contract-fixes` | `d61592b` | `6597799` | docs 17, 31 (CN-27): the API contract matches the server |
| #99 | `docs/security-limits-and-routes` | `a2630f1` | `ff36180` | docs 21: the security page matches S1 (the login limits, the routes) |
| #100 | `docs/qa-backend-merged-status` | `9eb383f` | `0381f55` | the backend review says which fixes are merged |
| #101 | `tests/server-state-rows` | `89d7516` | `1aa385d` | server: 24 state rows proved by tests that name them (ratchet 61 to 37) |
| #102 | `tests/server-state-rows-2` | `305ed85` | `4a4adb5` | server: docs/34 rows proved (ratchet 37 to 16) |
| #103 | `docs/readme-planned-features` | `3dda4cf` | `85e1747` | README says which features are planned |
| #104 | `docs/open-questions-of-the-coherence-pass` | `8ff24c5` | `23c326c` | the OPEN lines (08, 10, 23, 06) and the audit status |
| #105 | `app/downloaded-releases-share-songs` | `8143d29` | `82f75a8` | app: a song two downloaded releases share is listed in both (Phase 4, test first) |
| #106 | `docs/ci-matches-the-workflows` | `ab6bce0` | `c8a6556` | docs 06, 05: the CI section lists the workflows that exist |
| #107 | `docs/state-rows-after-the-phone-batch` | `5386faa` | `a7d9877` | docs 31 to 34: the one calm strip (D-45), the refused offline tap (D-42), D-46; CN-4b and PB-F7b Built; tests named for 11 more rows; the ratchet goes 15 to 4 |
| #108 | `docs/design-notes-the-calm-strip` | `1d2bf30` | `b00700d` | docs 04, 08, design/00, 02, 03 |
| #110 | `ci/goldens-commit-back` | `ab63720` | `8f95e86` | ci: goldens, alone (above) |
| #111 | `docs/data-model-matches-the-schema` | `d35aa47` | `da5db9b` | docs 04, 18: the data model against the migrations |
| #112 | `docs/layout-is-the-real-one` | `bf0310f` | `8fe6bbf` | docs 05, 06, 11, 15, design/00 and a comment of `tools/check.ps1`: the repository layout is the real one; an OPEN line in 06 §6 |
| #113 | `docs/gaps-the-code-closed` | `3681fb4` | `f4d1408` | docs 32, 34: D-2 and CF-11 say what is now true |
| #114 | `docs/minsdk-decided-not-applied` | `9c059f4` | `15658cd` | docs 02, 28: minSdk 26 is decided and not applied (the build uses Flutter's default, 24): an OPEN line |
| #115 | `docs/small-facts-in-11-07-06` | `4ae255b` | `d5eb810` | docs 11, 07, 06, README: the password rotation, three status headers, versionCode, the evidence list |
| #116 | `docs/roadmap-task-lists` | `c8b4787` | `422ef65` | docs 08: the task lists name P2-18 to P2-20, P3-12, P4-16 and P4-17 |
| #117 | `docs/notification-wording` | `cb19117` | `17c6244` | docs 20, 03a: new releases are a bell entry, no phone notification by default (ADR-R44) |
| #109 | `tests/typed-form-rows` | `538cbc2` | `d13675e` | app: tests for the typed sign-in form (CN-30, CN-31, JN-2, JN-9), each shown to fail when the matching line of `connect_screen.dart` is changed; the ratchet goes 4 to 0; main's Hygiene run for it is green, its App run (`d13675e`) was still going when this was written |
| #118 | `docs/rc-says-what-is-merged` | `1cc1986` | `456a38a` | RELEASE-CANDIDATE: a status line above the table of blockers says what is on `main` |

**Where the counts stand.** `python -I tools/check_rows.py` finds a test for **every** Built row (152 rows on `main` after the second order); the ratchet in `docs.yml` is **0**, so a row marked Built must bring its test. Phase 3 is done. Phase 4: the `released` map is #105; the track menu's "Removed" for a song another pin still wants is already fixed by the phone batch (commit `cd18643`: "stays on this phone: it is part of a downloaded playlist or album", test in `song_menu_download_test.dart`), nothing left to do.

**Noticed, not fixed** (none is a regression of this work; the earlier items 1 to 3 were settled by the second order, below):
1. A song downloaded on its own (song menu) that is also in a downloaded release is not told apart from the release's pin (there is one pin row per song): taking the release off takes it with the release. Written in `docs/33` PB-39. Telling them apart needs the saver to record which pins it created, a change to the phone's stored record: for the advisor.
2. The new wrong-key line can show once on a friend's Wi-Fi: the saved home address may be a stranger's web server there, and for a phone that knows its server's key any answer that is not the server is "another server". It is said once per outage, like the old sentence. Whether it should stay longer or be quieter is the advisor's.
3. Hygiene does not run for the Goldens workflow's own commit (a push by `GITHUB_TOKEN` starts nothing): the procedure says to run `tools/check_rows.py` by hand before merging.
4. The PC gate (`tools/check.ps1`) has not run on anything merged today; the next local session should run it once on `main`.

**OPEN (needs owner/advisor), each also written in the document concerned:** `docs/15` page 6 (the wizard page: runs the Tailscale sign-in itself, or shows the Host `encore funnel on`) and D-19/D-20 (the wizard's "Where songs come from" step and its "No YouTube account needed" line): both **stay open, tied to the owner's public-address question** (D-48 f); `docs/06` section 6 (the documentation rules name folders and a file length the practice does not keep); `docs/19` section 4 (the search-timing target N7: 300 ms cannot hold with a 400 ms fast phase). **Settled by the second order (D-48):** tablets (parked, D-18), the missing decision rows, the merge and pass rules (a pointer in `AGENTS.md`), the notification switches and minSdk (RC2, no code change before the QA rounds), the wrong key (restored). The two owner questions above (the public address, the history) are still only here.

**Not done** (`DOCS-AUDIT-2026-11-01.md` lists them): PB-F9 and G-2 (does the engine's one quiet retry take a fresh signed address? read the engine's retry path, then write a test that names the row), the ids D1 to D7 of ADR-R40, and the parts of slice 2 items 7 and 9 that the audit lists beyond what #92, #95, #98 and #103 checked. Not touched on purpose: `rc2/*`, `integration/*`, anything of RC2, any APK, tag or emulator work.

**This session's environment, for the next one:** Flutter 3.47.7 was installed in the cloud session's scratch space (the tarball checked against Google's sha256; gone with the session). `dart format` needs `flutter pub get` first or it formats in a newer style (see `docs/guides/dev-gotchas.md`). A step name in a workflow containing `: ` breaks the YAML: load a changed workflow with a YAML parser before pushing it. **Actions:** about 690 minutes since 2026-11-01 (the sum of the job durations of the 136 runs since that date, each job rounded up to a whole minute, skipped jobs not counted; the docs PR's own checks and the runs still going add about 25), against the order's cap of about 1,200 for the week.

### The advisor's second work order (2026-11-01, evening)

**Decisions recorded** as "decided by the advisor, 2026-11-01, reversible" in `docs/10`, row **D-48** (PR #122, `4794ce5`), together with the rows that were missing (D-21, D-22, D-45 to D-47): (a) tablet-specific layouts are parked everywhere, as the owner's D-18 says (`03`, `03a` US-75, `08`, P4-11 now also in `tasks/P6-later.md`, `14` U1, ADR-R42 point 5); (b) the missing rows; (c) `AGENTS.md` points to `tasks/RELEASE-CANDIDATE.md` section 1; (d) the notification switches (three in the app, ADR-R44 says two) and minSdk (24 built, 26 decided) are **RC2**, no code change before the QA rounds; (e) a wrong server key keeps its own line in the strip (built, below); (f) wizard page 6 (`15`) and D-19/D-20 **stay OPEN**, tied to the owner's public-address question.

**The order, item by item** (head, then merge on `main`):

| # | Item | PR | Head | Merge | Result |
|---|------|----|------|-------|--------|
| 1 | `removeDownload` unpinned songs another downloaded release still wants | #120 | `888b46a` | `f727815` | Test first (it failed on the old code). A song two downloaded releases share stays until the last release that wants it goes; the release page says "One song stays: another downloaded release has it." Rows PB-39 and, for finding F59, PB-40 in `docs/33`, with tests that carry the ids |
| 2 | a wrong server key (CN-11, CN-34, O-6) | #121 | `bb0a5f3` | `8770219` | Test first. `ConnectionProblem.anotherServer`, taken from the identity verdict kept per address by the session's probe and named by the endpoint resolver when no address proves itself; the strip says "Another server answers at <host>." once, with the cross; the player treats it as the server being away. 2,157 tests pass locally; three mutations each fail the matching tests |
| 3 | the three dots on artist rows | (in #122) | | | No code: the collection menu has **nothing for an artist** (no songs, and "Go to artist" only for an album's artist), so the dots would open an empty sheet. D-26's wording "every Library row" is corrected to "every row that has a collection" (Liked Songs, a playlist, an album); the code and the golden were already right |
| 4 | the mechanical docs leftovers | #123 | `a09f4c0` | `69e6246` | slice 1 items 23, 25, 26, 28, slice 2 item 10, the cells of `RELEASE-CANDIDATE` and `AUDIT`; P2-21 is written; the search-timing target (N7) is an OPEN line in `19` |
| 4 | the row for CF-38 (a shared device, two profiles, one outbox) | #124 | `9488a36` | `bdd1089` | Read from the code and proved: only the active profile delivers; a profile switched away from waits untouched and uses no attempt. Five tests named `CF-38: ...`, two mutations |
| 5 | does an installed server update itself from `main`? | this entry | | | **No.** See below |

**Main after the order.** Main's own runs for `bdd1089` (one App run covers #120, #121 and #124: each later app push cancelled the older App run of `main`, as designed) are green: Hygiene, App `verify` and the Android debug build (`android-debug-build`, finished 18:00 UTC). Not run by anyone: the PC gate (`tools/check.ps1`), the emulator, an APK, a tag.

**Does an installed server update itself from `main`? No, and the next local session must know what it would get before Monday.**
* An installed server follows the image `ghcr.io/appayiipyiip/encore-server:main` (`ENCORE_TAG=main` in `/opt/encore/.env`; the installer's default; `compose.yaml` says `${ENCORE_TAG:-main}`).
* **Nothing pulls by itself.** `compose.yaml` has no updater (no Watchtower, no `pull_policy`); the only timer the installer makes is the nightly backup (`encore-backup.timer`); `restart: unless-stopped` and `docker compose up -d` (which `encore funnel on|off` also runs) reuse the image already on the disk. A newer image reaches a running server only when somebody runs **`encore update`** (a backup first, then `docker compose pull`, then the compose file and the `encore` command out of the new image, then a restart), re-runs `install.sh`, or pulls by hand. The image is private while the repository is, so a pull needs a GitHub token with `read:packages`, which the installer asked for. The one thing a running server does update by itself is yt-dlp (`ENCORE_AUTO_TOOLS=1`, ADR-R39: a daily check, a canary, a switch at the next start).
* **When the registry's `:main` moves** (`server-image.yml`): on every push to `main` that touches `server/encore_server/**` or the workflow, after the server tests pass; **every Monday 04:17 UTC** (a rebuild without the layer cache and without tests, for yt-dlp and base-image fixes; GitHub started the last one on 2026-10-26 at 10:13 UTC, six hours late); on a `v*` tag; by hand. The next scheduled build is **Monday 2026-11-02, about 04:17 UTC or later**. It republishes `:main` from the newest `main`, which today's pushes have already put there; it changes nothing on a running server.
* **What `:main` holds now:** the build of `4a4adb5` (2026-11-01 14:41 UTC) with S0 to S3 and W-05; the merges since then touch only the app and the documents. The image before that was built on 2026-10-30 at 14:08 UTC (`c8a1853`).
* So the owner's own server runs today's server code **only if somebody has run `encore update` (or reinstalled) on it since 14:41 UTC today**. The repository cannot show that: on the machine, look at the creation date of the local `ghcr.io/appayiipyiip/encore-server:main` (`docker image inspect`), at `encore status`, and for a Watchtower or a cron job the owner may have added by hand.
* **What an older app would meet on the new server** (read from the diff of `api.py`, `auth.py`, `gateway.py`, `live.py` and `accounts.py` between the server of 2026-10-30 and now; **no older app was run against it**): wrong passwords are slowed (5 a minute for one name from one address, 30 for one address) and no longer lock an account after 20; a locked account is refused before its password is looked at; the signed song and cover addresses of a removed or locked person stop working; a device that is signed out, revoked, locked or removed has its live connection closed with code 4401, and a changed password closes the other devices' live connections; `X-Forwarded-For` is read from the right and only from our own proxies; through the public address only the music server's Subsonic API (`/rest`) is passed on; request bodies are limited (4 MiB for the server's own API, 1 MiB passed on); `GET /encore/join/<code>` is a new page, and a join whose answer was lost can be repeated. `API_VERSION` (1.0), `MIN_APP_VERSION` (0.1.0) and the database migrations are unchanged: nothing an older app asks for was removed, and there is no schema step to undo.

### The design page and `docs/design` (2026-11-01, night, after the second order)

The owner sent the page "Encore Design Choice" with "more incoherence that needs to be fixed". It was read against `docs/design/*`, `docs/10` and the built app (not against the drawings: D-43 makes them history wherever the app has the screen). Found, and fixed in this pull request:

* **The page contradicted itself.** One card called the drawing "the revised version ... Your server is redrawn" while the section above it said nothing was redrawn after 24 and 25 October and that Now playing and Your server carry known differences. One story now: the drawing has the changes asked for on 24 October, was not redrawn since, and those two frames are read with the list of differences.
* **"Taken out" was ambiguous.** The device icon, the share icon, the speed control and the test button are drawn and the app has none of them; the page said they were "taken out" as if the drawing had been edited. Reworded in the list and in "What you said".
* **Two differences the page did not list:** the Home avatar (top right in the drawing, top left in the app: `home_screen.dart`, and the drawing's header) and Settings > Notifications (two categories drawn, three switches in the app, RC2 by D-48 d). **Three things it offered without saying they are parked:** the web player (D-18), the car display, and tablets (D-48 a). The date line says 1 November.
* **`00-screen-inventory.md`** said every screen is drawn at C, X and T (M and T are parked); called What's new (#35) and the profile menu (#60) "new" though built; described the device and share icons and the speed menu for S-31 and S-35, and a "Test the connection" button for S-71; gave two notification categories for S-72 without the RC2 note.
* **`03`** carried three decisions that were reversed later without a note (the test button, the device and share icons and speed, the three notification switches); the "final consistency pass" it asks for is closed without being done, by D-43. **`04`** said the app is changed to match the frames (void by D-43), named a file that is removed, and had a snapshot "Built" column with no note of what was built since (#63, #88, the Library menus, #60, #35); a status paragraph now says so, and explains "62 screens, 299 states" against the 654 frames in the five files (120 + 172 + 130 + 164 + 68, counted; the page's own counts for four of them match). **`02`** "Next" items 1 and 2 are marked done. **`README.md`** lists the page and says the app wins where they disagree.
* **The page had no source in the repository** (it existed only as an artifact). Its text is now `docs/design/directions/index.html`, a full document; the artifact is the same text without the skeleton.

**Noticed, not fixed:** `speed_sheet.dart` is not opened by any menu since D-23 but is still in the code with `speed_test.dart`; whether to delete it with its test is the advisor's. The five drawing files were not touched, so their frames still show what the page lists (D-43).

## 0. First thing to do: report what this session can do, then stop

Before touching anything, answer in a short list and wait for the owner's go:

1. Can it push a branch it did not create (for example `task/S0-ci-hygiene`) to `origin`? Can it use `gh` (open a PR, `gh run list`, `gh pr merge N --squash --match-head-commit <sha>`, `gh workflow run goldens.yml`)?
2. Is Flutter installed (`flutter --version`), and Python 3 with the server's test dependencies?
3. Can it reach the internet beyond GitHub (it will not reach the owner's machines: that is expected)?

If it can only push its own session branch, the merge sequence in section 3 cannot be done from here: say so, and the owner merges the PRs in the GitHub page, or a local session does it.

## 1. Rules that did not fit in the memory of a new session

* **Never make the repository public** and never put the owner's first name, addresses or machine names in it. A scrub is planned and is the owner's decision.
* **Never print or commit a password, token or key.** There are none in the repository; do not look for them.
* **At most two agents at a time** (a usage limit was hit with four).
* **Do not work in the cloud and on a local machine on the same branches at the same time.** Whoever starts next begins with `git fetch`.
* **A state is a row.** Touch a state in `docs/31` to `34`, update its row (`tools/check_rows.py`; the ratchet in `docs.yml` is 0: a Built row brings its test). A row whose test is only on an unpushed branch must not say "Built".
* **Merge only when every check on the PR head has finished green**, with `gh pr merge N --squash --match-head-commit <full sha>`; never `--admin`; poll `gh run list --branch <b>` (not `statusCheckRollup`). Squash-merge each PR under an area title (`app: ...`, `server: ...`, `docs: ...`).
* Everything below is **built and tested, not walked** on a phone.

## 2. Where the code is

`main` (docs only since 30 October) is behind. Everything else is on `origin` under the prefix `backup/` (66 branches, pushed 2026-11-01, no CI runs on them). Make them local branches first:

`git fetch origin "+refs/heads/backup/*:refs/heads/*"`

| Branch | Tip | What |
|---|---|---|
| `task/B2-one-entry-per-release` | `2c924ec` | PR #63 (open, five checks green at this tip) |
| `task/RC1-app-batch` | `dfbdbac` | the phone batch: 20 commits on #63's tip; wide suite 2,143 passed, 1 skipped |
| `task/S0-ci-hygiene` | `f1d7757` | B25 image only on main/tags after tests, B28, B27, the D-44 CI cuts |
| `task/S1-public-edge` | `2e2b823` | public-edge fixes (B1, B2, B12); do not turn the public address on for anybody before this is merged |
| `task/W05-join-page` | `309ebbd` | the join page and B15, stacked on S1 |
| `task/S2-silent-failures` | `749d423` | B8, B7 |
| `task/S3-revocation` | `21c25f1` | B4, B5, B13, B6, stacked on W05 |
| `integration/qa-round-1` | `86181b2` | S0, S2, S3 stack merged (what the dev server ran) |
| `rc2/B34-timeout-retries`, `rc2/Q3-track-positions`, `rc2/F58-like-in-notification` | `e9a6288`, `8f9247a`, `ba6aba1` | parked for after the release candidate |
| `docs/coherence-pass-1` | `f7939a0` | a half-done rewrite of `docs/22` (backups); review before using |

What the phone batch adds (since PR #63): the owner's missing Invite someone and People tiles (R1-1: the first "who am I" ask of a session ran before any address had proved itself), "Play any song" stuck on "did not answer", downloads left on the phone after a downloaded playlist is deleted (a removed pin is removed at once), one missing song stopping a playlist when the phone has a network and no data (`canReachServerNow`, one shared look at the server before a refusal, Play and Shuffle start at a downloaded song), one calm connection strip per outage, lyrics that spin for ever or show a tag sheet, the music held when a failure makes the platform player hop to the next song, a Wi-Fi sign-in page never read as the server, phones locked to portrait, the code review's real findings. Detail: `QA-ROUND1-2026-10-31.md`.

## 3. The push, in order (about 420 of 3,000 Actions minutes; the minutes reset on 1 November)

Replay first, in a throwaway worktree on current `origin/main`: `git merge --squash origin/task/B2-one-entry-per-release`, commit, `git cherry-pick 2c924ec..task/RC1-app-batch`; run `flutter analyze` and `flutter test` in `app/`. It replayed with no conflict on 2026-10-31.

1. **S0** (`task/S0-ci-hygiene`): open the PR. A PR runs its own (new) workflow files: this is their **first real run**, so read each job (`server-image.yml` tests and image, `app.yml` conditions, `docs.yml`, `server-legacy.yml`). If one is wrong, fix it on a small branch. Merge, then watch `main`'s own run.
2. **#63**: merge right after S0 if its checks are still green and it is not conflicting; otherwise rebase onto `main`, push, wait.
3. **S1**; 4. **W-05** (after S1 is squash-merged: `git rebase --onto origin/main 2e2b823 task/W05-join-page`, force-with-lease, PR);
5. **The phone batch** (after #63: `git rebase --onto origin/main 2c924ec task/RC1-app-batch`, push, PR). Then redraw **two** Linux goldens, `library_list` and `now_playing_waiting` (their Windows versions changed): `gh workflow run goldens.yml --ref <branch>` and commit the result to the branch; then merge.
6. **S2**; 7. **S3** (after W-05: `git rebase --onto origin/main 309ebbd task/S3-revocation`).
8. Tag the green `main`. Then the release-candidate pair (section 4).

A failing check is fixed on the PR's branch, never merged red. A red `main` run is fixed at once by a small PR; nothing else merges until `main` is green. Pushing a branch named `task/...` with changes under `server/encore_server/` also runs the server-image workflow (it can publish a task image): push server branches only when you mean it.

## 4. What can be done where

**In the cloud (if section 0 allows):** the push and merge sequence above (CI runs on GitHub); the **docs coherence pass** (two audits, `DOCS-AUDIT-2026-11-01.md`, about 70 contradictions: do it in small PRs, run `python -I tools/check_rows.py --max-missing 0`); server-side tests and fixes; tests for the "Built" state-table rows (done: every one has a test); the RC2 leftovers from the code review (done: the `released` map is #105, the track menu and the strip are in the phone batch); parked RC2 code if the owner asks.

**Local only (emulators, the dev servers, a hypervisor over ssh):** QA rounds 2 and 3 and the critic (two Android emulators); building any APK that will be installed on a phone (the signing key is on the owner's PC, a different key cannot update an installed app); deploying the integration build to the dev VM; the clean-VM install test (needs the published image and a Proxmox VM); anything on the owner's own server VM or phone.

## 5. The rest of the plan, in order

After the pushes: the release-candidate pair (APK with `--build-number=N --dart-define=BUILD_NUMBER=N --dart-define=GIT_SHA=<sha>`, N 125 or higher; the server image from `main`) -> **QA round 2** (build 124 was started and cut short; the tester must also walk the states people live in: server stopped while the phone has Wi-Fi, a partly downloaded playlist, a deleted downloaded playlist, a ten-minute outage; `docs/07` section 5) -> fix test-first -> **QA round 3** (J1 to J13 with the browser step of the invitation link) -> the **clean-VM install test** -> the **critic** (an ordinary Spotify user; the raw list goes to the owner unfiltered). Then tag, a new bundle, and the friend guide once the public address is proved.

Open problems the owner reported on his first real-phone test: the server sign-in page after a glimpse of public Wi-Fi (cause unknown; the router now logs a line), and the previous title under the next song (a mechanism was found and fixed in the engine, unconfirmed on a phone). Away from home the phone cannot reach the server on purpose (the public address is off until S1 is merged).

## 6. Questions for the owner, asked once and only these

* Turn the public address (Funnel) on after S1 is merged? (it exposes his server to the internet; give him the risks)
* Scrub the history and publish the repository? (not needed: the minutes reset; irreversible; his tailnet name, first name, real artist names in the design drawings and machine names are in the history)
* Nothing else. In particular: do not ask him to test, and do not ask which build his phone runs.
