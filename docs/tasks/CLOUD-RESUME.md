# Resume from the repository alone (written 2026-11-01, the day the weekly usage limit ran out)

For a session that starts with **only this repository** (Claude Code on the web, or a new PC): it has none of the earlier session's memory. Read `AGENTS.md`, `docs/README.md`, then this file, then the last log entry (22) of `RELEASE-CANDIDATE.md`. The owner is not a tester and is not asked to test; he is asked only what only he can decide (section 6).

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
