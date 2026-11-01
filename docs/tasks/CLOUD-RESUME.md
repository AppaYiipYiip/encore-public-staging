# Resume from the repository alone (written 2026-11-01, the day the weekly usage limit ran out)

For a session that starts with **only this repository** (Claude Code on the web, or a new PC): it has none of the earlier session's memory. Read `AGENTS.md`, `docs/README.md`, then this file, then the last log entry (22) of `RELEASE-CANDIDATE.md`. The owner is not a tester and is not asked to test; he is asked only what only he can decide (section 6).

## Work order

Given by the owner on 2026-11-01 after the section 0 report, copied word for word. It replaces the "stop and wait" of section 0 and the merge order of section 3 (the phone batch is now merged last). Progress, below it, is the channel to the next local session and to the owner.

STANDING WORK ORDER (you can work from this for a long while without asking me anything; if you are unsure, choose the safer option and record it in Progress). STEP 0, FIRST: in your first docs PR copy this whole order into docs/tasks/CLOUD-RESUME.md as a section "Work order" with an empty section "Progress" under it; after every merge and at the end of every phase update Progress (on main, through a small docs PR; you may batch these) with PR numbers, merge shas, the head sha of any branch you pushed, and what is blocked and why: Progress on main is the channel to the next local session and to the owner, not this chat, and it survives your context being compacted.

PHASE 1, MERGES in this order: S0, #63, S1, W05, S2, S3, then the phone batch last (S2 and S3 are server-only and must not wait for a goldens or Flutter problem); follow CLOUD-RESUME section 3 for commands; merge only after every check run on that exact head sha is green, via gh api PUT pulls/N/merge with merge_method=squash and sha=<full head sha>, area-prefixed title, then read main's own run. The S0 PR (84) is all green now: merge it first, and check whether your encore-fetch test fix already covers the flaky legacy test (test_stops_looking_when_the_service_has_stopped) before doing anything else about it. For the server branches: pip install the server dependencies and run ruff, mypy and pytest --ignore=tests/integration in server/encore_server before pushing any rebased branch; resolve purely mechanical rebase conflicts (imports, adjacent lines, docs) yourself and rerun the suite; stop on a conflict only where choosing a side changes behaviour. For the phone batch CI decides: if anything other than the two Linux goldens (library_list, now_playing_waiting) goes red, install Flutter 3.47.7 in the session and work the failure locally before pushing again; if the redrawn goldens cannot be delivered, leave the PR open with everything else green, write it in Progress and move on.

PHASE 2, DOCS COHERENCE PASS from docs/tasks/DOCS-AUDIT-2026-11-01.md: small PRs, one family of files each, run python -I tools/check_rows.py --max-missing 61 before each, flip a "Decided ... not on main yet" row to Built only once its test is on main (after the phone batch merges), reuse the docs/22 draft on backup/docs/coherence-pass-1 only after checking it against ADR-R37 and the code, and for a real product choice write an "OPEN (needs owner/advisor)" line in the doc and in Progress and do not decide it.

PHASE 3, TESTS for state-table rows that have none: server rows first (pytest runs here), then app rows with Flutter installed locally, batched into few PRs so Actions minutes are not spent one PR at a time; whenever the untested count drops, lower --max-missing in docs.yml in the same PR.

PHASE 4, the small code-review leftovers, test first: the released map in the download providers keeps one release per song, the track menu says Removed for a song that is still wanted by another pin, and nothing else; then stop. Do not touch rc2/*, integration/* or any RC2 feature.

HARD RULES: never make the repository public, never admin-merge, never force-push main, never delete branches, no tags or releases (read the server-image.yml triggers first: a tag may publish an image), no workflow edits except to repair a broken one, no pushes to branch names matching task/**, no secrets, no billing, keep total GitHub Actions use this week under about 1,200 minutes including the merges, at most two agents at a time.

WHEN BLOCKED: write it in Progress and go on to the next independent item; stop completely only for a red main you cannot fix at once, a security question, or credits about to run out. The two owner questions (turning the public address on after S1, and scrubbing the history before publishing) go only into Progress, never ask them. Post two lines in this chat at the end of each phase.

## Progress

<!-- One entry per merge and per phase, newest last: PR number, merge sha, the head sha of any branch pushed, and what is blocked and why. -->

### Phase 1, merges (2026-11-01)

Every PR below was squash-merged with `gh api PUT pulls/N/merge` and `sha=<head>` after every check run on that exact head was green. The rebased server branches were checked locally first (`ruff check`, `ruff format --check`, `mypy encore_server`, `pytest --ignore=tests/integration` in `server/encore_server`, all clean) and were pushed only to the session branch `claude/zealous-maxwell-7s5nio`; no `task/**` branch was pushed.

| # | PR | Merge sha on main | Head that was merged | What | main's own run |
|---|----|-------------------|----------------------|------|----------------|
| 1 | #84 | `8b7cb8a` | `b92d6bb` on `backup/task/S0-ci-hygiene` (the S0 commits plus one of mine) | S0: CI cuts (D-44), the server image only after tests on main and `v*` tags (B25), B27, B28 | Server, Server legacy, Hygiene and Server image green (first real run of the `tests` and `image` jobs); App `verify` green, its Android build cancelled by the next merge's push |
| 2 | #85 | `c42d411` | `72d7f18` on the session branch | this work order | Hygiene green |
| 3 | #63 | `513d875` | `2c924ec` on `task/B2-one-entry-per-release` | B2 second half: a downloaded release is one entry | Hygiene green; App run still going at 13:46 UTC (see the next entry that mentions it) |
| 4 | #86 | `9aba607` | `2e2b823` on `backup/task/S1-public-edge` | S1: the public edge (B1, B2, B9, B11, B12, B19) | Server, Hygiene and Server image green |
| 5 | #88 | `b90435b` | `2a1995f` on the session branch (W05 rebased with `git rebase --onto origin/main 2e2b823`) | W-05 join page (D-39), B15 | Hygiene green; its Server runs were cancelled by the next push, whose run covers it |
| 6 | #87 | `9ba6dd4` | `749d423` on `backup/task/S2-silent-failures` | S2: B8 (no search while YouTube rests, every search counted), B7 (a never-found file ends as a failed keep) | Server, Hygiene and Server image green |
| 7 | #89 | `4b9d957` | `f728c61` on the session branch (S3 rebased with `--onto origin/main 309ebbd`) | S3: B4, B5, B13, B6 (revocation) | Hygiene green; Server and Server image still going at 13:46 UTC |

What else happened, for the next session:

* S0's first real run showed one red: `test_stops_looking_when_the_service_has_stopped` in `server/legacy/encore-fetch` (the same assertion had failed on main on 2026-10-25, run 40153063719). Cause: the fake service lived 2 s and the update loop looks every 1 s, so the loop's second look fell exactly when the service ended. Fixed on S0's branch (commit `b92d6bb`, only the timing of the test: the service lives 3 s, the loop looks every 2 s; the assertion is unchanged). Checked: 2 of 20 runs failed before, 0 of 20 after, and the test still fails (`7 != 4`) when the loop's `kill -0` guard is removed from `entrypoint.sh`. Someone also re-ran the first attempt of the legacy workflow on GitHub; that does not remove the cause.
* On main before S0, `pytest` could fail in `test_account_model.py` when Hypothesis found a lock followed by an unlock (the model said the device works again, the server correctly kept it dead). That is B28, fixed by S0.
* The B25 change works: pushing to main ran `tests` and then `image` and published the image to the private registry; a task branch no longer builds one.
* #63 was merged as soon as S0's `verify` job on main was green. Its push cancelled S0's Android build through the workflow's own `cancel-in-progress`; #63's run builds the APK on the combined tree.
* `tools/check_rows.py` reports 60 Built rows with no test on main at `4b9d957` (S1's docs edit made CN-25 cite its test); `.github/workflows/docs.yml` still says `--max-missing 61`. The ratchet is lowered in the Phase 3 PR, together with the tests.
* GitHub Actions used since 2026-11-01: about 187 minutes over 41 runs at 13:46 UTC (job durations rounded up to whole minutes; runs still going are not counted).
* Decisions taken without asking: every rebased branch went through the session branch and no other branch was created; the session branch is reset to `origin/main` and force-pushed with a lease after each merge (it holds no work that is not on main).

OWNER QUESTIONS (recorded here only, not asked):

1. Turn the public address (Funnel) on? S1 (B1, B2, B9, B11, B12, B19) and S3 (B4, B5, B13, B6) are merged, but two things stay open: whether the Funnel really sets `X-Forwarded-For` as B11 assumes (only checkable on the owner's Funnel), and narrowing `/rest`; the app also still sends the old login, not the Bearer token. Turning it on exposes the owner's server to the internet. `docs/guides/install-test.md` step 5 tells a person to run `encore funnel on` without this warning.
2. Scrub the history and publish the repository? It is not needed (the Actions minutes reset); it cannot be undone; the history holds the owner's tailnet name, first name, real artist names in the design drawings and machine names.

Blocked: nothing yet. Next: the phone batch (rebase `task/RC1-app-batch` onto main; CI decides; two Linux goldens, `library_list` and `now_playing_waiting`).

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
* **A state is a row.** Touch a state in `docs/31` to `34`, update its row (`tools/check_rows.py`, ratchet 61). A row whose test is only on an unpushed branch must not say "Built".
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

**In the cloud (if section 0 allows):** the push and merge sequence above (CI runs on GitHub); the **docs coherence pass** (two audits, `DOCS-AUDIT-2026-11-01.md`, about 70 contradictions: do it in small PRs, run `python -I tools/check_rows.py --max-missing 61`); server-side tests and fixes; writing tests for the 61 "Built" state-table rows that have none; the RC2 leftovers from the code review (the `released` map keeps one release per song; the track menu says "Removed" for a song still wanted; the strip says "offline" when only the server is down); parked RC2 code if the owner asks.

**Local only (emulators, the dev servers, a hypervisor over ssh):** QA rounds 2 and 3 and the critic (two Android emulators); building any APK that will be installed on a phone (the signing key is on the owner's PC, a different key cannot update an installed app); deploying the integration build to the dev VM; the clean-VM install test (needs the published image and a Proxmox VM); anything on the owner's own server VM or phone.

## 5. The rest of the plan, in order

After the pushes: the release-candidate pair (APK with `--build-number=N --dart-define=BUILD_NUMBER=N --dart-define=GIT_SHA=<sha>`, N 125 or higher; the server image from `main`) -> **QA round 2** (build 124 was started and cut short; the tester must also walk the states people live in: server stopped while the phone has Wi-Fi, a partly downloaded playlist, a deleted downloaded playlist, a ten-minute outage; `docs/07` section 5) -> fix test-first -> **QA round 3** (J1 to J13 with the browser step of the invitation link) -> the **clean-VM install test** -> the **critic** (an ordinary Spotify user; the raw list goes to the owner unfiltered). Then tag, a new bundle, and the friend guide once the public address is proved.

Open problems the owner reported on his first real-phone test: the server sign-in page after a glimpse of public Wi-Fi (cause unknown; the router now logs a line), and the previous title under the next song (a mechanism was found and fixed in the engine, unconfirmed on a phone). Away from home the phone cannot reach the server on purpose (the public address is off until S1 is merged).

## 6. Questions for the owner, asked once and only these

* Turn the public address (Funnel) on after S1 is merged? (it exposes his server to the internet; give him the risks)
* Scrub the history and publish the repository? (not needed: the minutes reset; irreversible; his tailnet name, first name, real artist names in the design drawings and machine names are in the history)
* Nothing else. In particular: do not ask him to test, and do not ask which build his phone runs.
