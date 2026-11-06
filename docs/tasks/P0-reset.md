# P0 — Reset (no product changes)

Goal: a clean, safe, honest repository and process. Read `../05` first (where it started, and the target layout).

---

## P0-01 to P0-05 — done (kept as a record)
* **Order.** Needs: none.
* **P0-01 Secrets out of git.** Done. Login files live in `..\local\logins\` and are never committed; the pre-commit hook refuses
  `*login*` files, `.env`, keys and APK/AAB files. No password rotation (owner, 2026-10-21: the test passwords are temporary).
* **P0-02 The homelab folder leaves the repository.** Done. Nothing of the owner's homelab is in this repository; the scripts that
  were homelab-only are in `Desktop\homelab\encore-era-scripts\` (the owner's project).
* **P0-03 Workspace clutter.** Done 2026-10-22. The workspace holds `encore/`, `local/`, `releases-archive/`, `backups/`, `.claude/`
  and `CLAUDE.md`.
* **P0-04 The new repository.** Done. `encore/` was made from a cleaned tree and the old repository's full history is the verified
  bundle `releases-archive/old-repo-2026-10-22.bundle` (its uncommitted service-finder work is archived next to it: superseded by ADR-R3).
* **P0-05 Rename, re-icon, licence.** Done. Android package and namespace `app.encore.player`, pubspec `name: encore`, a temporary
  launcher icon (green waveform on dark), GPL-3.0 `LICENSE`, `README.md`, `CHANGELOG.md`, `SECURITY.md`, `PRIVACY.md`.

## P0-06 — CI for the app and the server
* **Order.** Needs: none.
* **Why.** D7.
* **Do.** `.github/workflows/app.yml`, `server.yml`, `docs.yml` as in `../06` §7 (release.yml comes in P5-01). Flutter version pinned
  (the one in today's `ci.yml`: 3.47.7). Python 3.12; run each legacy server suite (`python -m unittest discover`) until P3-01 replaces them.
  Path filters so app changes don't run server jobs. Cache pub and pip.
* **Acceptance.** A PR that breaks a test is red; the first PR on the new repo is green; run time app ≤ 15 min, server ≤ 10 min.
* **Size.** M.

## P0-07 — GitHub set-up
* **Order.** Needs: none.
* **Open inside this task (2026-11-04).** Only one thing is left: protect `main` (a GitHub setting, the owner's). The GitHub project board and one issue per task are **dropped**: the owner does not use GitHub, and the roadmap board (`docs/roadmap/`, `roadmap.bat`) replaces them. The rules, decided by the advisor: a pull request is required with 0 approvals (he is the only person), the two checks that run on every change (`checks`, `secrets`) must pass (the others are path-filtered and would block documentation changes forever), no force push, no deletion. The exact clicks are pinned on the item.
* **Why.** Owner: "the GitHub is shit, confusing and weird". `../05` §4.
* **Context.** Today: `AppaYiipYiip/encore`, private, default branch `better-audio-player` (stale since 2026-10-16, README emptied),
  branches `master` (the upstream project) and `work/eng-review` (with passwords), 16 upstream tags, no releases, no description.
* **Do.** (Needs D-8 for pushing.) Rename the old repo to `old-repo`, archive it; create the new `encore` (private), push `main`;
  description, topics; branch protection on `main` (PR + green CI + 1 review, no force push); labels and issue templates
  (`bug.yml` with the fields of `../06` §3, `feature.yml`); a Project board (Backlog/Ready/In progress/Review/Done); one issue per
  task in `tasks/`, linked.
* **Acceptance.** A visitor sees: a README that explains Encore in 30 s, only `main`, no foreign tags, issues and a board that
  match `tasks/`.
* **Depends on.** P0-04, D-8. **Size.** S.

## P0-08 — Files that guide agents
* **Order.** Needs: none.
* **Do.** `AGENTS.md` (copy of `../06` §5 + "read `docs/README.md` first"), `CLAUDE.md` with one line pointing to it,
  `.github/pull_request_template.md` (what changed for a person, evidence, setup measured on, not tested + why, checklist from
  `../07` §10), a `gitleaks` pre-commit hook and CI step, `.gitignore` for `*.apk *.aab *.env *login*.txt *cookies*.txt build/`.
* **Acceptance.** Committing a file named `x-login.txt` or containing an API-key-looking string is blocked locally and in CI.
* **Size.** S.

## P0-09 — Environments as code (first part) — Size M
* **Order.** Needs: none.
* **Why.** `../24` §2: every test environment rebuildable by one command; real data, legally.
* **Do.** `tools/env/stack up` (server + Navidrome + a seeded library of Creative Commons albums with real tags, covers and lyrics; licences
  listed), `tools/emulators/create A B C D E` and `profile <X>` from configs in the repo, `tools/fixtures/refresh` (recorded outside-service
  answers, ≤ 50 spaced calls). The VM and two-server environments come with P3-07 and P4-09.
* **Acceptance.** A fresh clone runs `tools/env/stack up` and the unit + integration suites against it with no manual step.

## P0-10 — Licence inventory and checks — Size S
* **Order.** Needs: none.
* **Why.** `../25`: a public GPL-3.0 project must know every component's licence and every service's terms.
* **Do.** Verify every *verify* row of `../25`; a CI step that lists Dart and Python dependency licences and fails on an unknown or
  incompatible one; `THIRD_PARTY_NOTICES` generation; About → "Open-source licences" in the app.
* **Acceptance.** CI green with the check; the table in `../25` has no *verify* left.

## P0-11 — CI upkeep and the toolchain — Size S
* **Order.** Needs: none.
* **Why.** Debts that pile up silently (`RELEASE-CANDIDATE.md` §5, `history/README.md#audit` P0, the audit of 3 Nov, A-17): GitHub's own annotations on a green run (Node.js 20 is deprecated for `actions/checkout@v4` and `setup-java@v4`, `setup-java@v4` itself is deprecated, `ubuntu-latest` is migrating to Ubuntu 26, the runner's NDK install flaked once); Gradle 8.14, AGP 8.11 and Kotlin 2.2.20 "will soon be dropped" by Flutter; mypy reports one unused `type: ignore` (`keeper/tagging.py`); issue #41 (a flaky account-model test) is fixed by B28 and still open; the tracker rule (use Issues or delete the rule) is undecided.
* **Do.** Move the actions to versions that run on Node 24 and to `setup-java@v5`; pin `runs-on` to a fixed image and make the NDK step retry; plan and do the Gradle/AGP/Kotlin upgrade before the first release (a branch that builds both APKs); remove the unused `type: ignore`; close #41 with the PR that fixed it; decide the tracker in one line in `AGENTS.md`.
* **Acceptance.** A run of every workflow shows no deprecation annotation; both APKs build on the upgraded toolchain; `main` is protected (P0-07, the owner's setting).
* **Two pull requests (advisor, 5 Nov 2026).** **A, CI upkeep:** every action on its Node 24 release (checked against each action's `action.yml`, not from memory), `runs-on: ubuntu-26.04` named on purpose (the `ubuntu-latest` label moves in November; this is a choice with a reminder, not a stop-gap), the Android build retries a failed download, `.github/dependabot.yml` (the actions, monthly, one grouped pull request), the tracker decided (D-60: the board). The "before" list is GitHub's real annotations on the latest green run of each workflow; the "after" is the same list empty. The unused `type: ignore` and issue #41 turned out to need nothing in code (see `RELEASE-CANDIDATE.md` section 5). **B, the Android toolchain** (done 5 Nov 2026; Gradle 9.3.1, AGP 9.1.0, Kotlin 2.4.0 = the versions of Flutter 3.47.7's own `flutter create` template, built-in Kotlin on, `wakelock_plus` 1.8 so that `package_info_plus` 10 no longer applies the Kotlin plugin; applicationId, signing and versionCode untouched; release builds of both processors, the x64 one installed fresh on an emulator, signed in to the test VM, a library song played and paused from the notification, and an in-place upgrade over build 125 checked; then the Android job and the Goldens workflow run by hand on the branch; a smoke test, not a walk): marked built in its own pull request. What is left on the board as reminders: the `android.newDsl=false` line (Flutter's own template carries it) and the toolchain diff to repeat at every Flutter upgrade.
* **Size.** S.

## P0-12 — Documentation honesty (the open items of the audit of 3 Nov) — Size S
* **Order.** Needs: none.
* **Why.** The audit of `main` on 3 Nov found documents that promise what the code does not do. Four are open: **A-1** `17` §2 says the Auth row is built while the app still sends `u/t/s` in the URL (the code fix is the Bearer move, P2-20 slice 3); **A-6** `CHANGELOG.md` lacks the ~25 user-visible lines (the AUDIT F-table already has them); **A-15** the guide must state the 2 GB / 6 GB the installer enforces; **A-16** `04` §7, `26` §2 to 3 and `06` §1's diagram need "(target; not built)" markers. (A-2, A-3 and A-7 are fixed; A-9 is the ratchet in `check_rows.py`.)
* **Do.** Make those four edits, each with the evidence line, in one documentation pull request.
* **Done (5 Nov 2026, checked again on `main` `3b2eb74`, not copied from the audit).** **A-1:** `docs/17` §1's Auth row already says "Target, not what the app does yet" (PR #128, `473a3b1`); the code still puts `u`, `t`, `s` in the URL (`app/lib/data/encore/encore_api.dart` `_uri`, lines 36-48), so the row is true as it stands: no edit. **A-6:** `CHANGELOG.md` has been rewritten by #128 (12 lines, each spot-checked against `main`'s code); two lines added for what merged since (songs without an album, #136; the old request page never offered on an Encore server, `fad1b45`). **A-15:** `docs/guides/install-test.md` states 2 GB and 6 GB (`deploy/install.sh` lines 135-140 enforce 1,800 MB and 6 GB) and now says what a stranger sees below them; AUDIT F28 no longer says "no minimum". **A-16:** #128 marked `docs/04` §7 step 2, `docs/26` §2-3 and `docs/06` §1; what was still unmarked is marked now: `docs/04` §1's picture (no `encore.local`, no admin app, no wizard), the multi-arch image claim (amd64 only), §7's wizard and admin page (the CLI is built: `deploy/encore`), and `docs/26` §6's SMART check. The issue and pull-request templates are reworded as an intake form for the board (D-60).
* **Acceptance.** For each item a reader can tell from the document what is built and what is a target.
* **Size.** S.

## P0-13 — Release candidate 1 walked (the walk record b11) — Size M
* **Order.** Needs: P1-01 [d], P1-02 [d], P1-05 [d], P1-06 [d], P1-08 [d], P1-11 [d], P2-02 [d], P2-03 [d], P3-01 [d], P3-04 [d], P1-15 [d], P1-16 [d], P2-22 [d], P5-01 [d], P1-18 [d], P1-19 [d], P2-25 [d], P2-26 [d], P1-21 [d], P3-35 [d], P2-28 [d].
* **Why.** This was the first gate of the old, phased plan (D-57 removed the phases, so it is a task now). The owner's definition of pass: nothing is "walked" until it is walked as a person on the release-candidate pair (the published image plus the app built from the same commit, signed with the release key) on a clean machine, to the end state; and nothing goes to the owner as ready until the walk record exists and the advisor and the critic have read it.
* **Do.** Rounds 2 and 3 of the walk (`RELEASE-CANDIDATE.md` section 3), written up as `b11`; the advisor reads it, then the critic; every built item it covers is marked walked (or reopened) with `python tools/roadmap.py mark`; the open round-2 findings are fixed or triaged "later" in `history/README.md#audit`.
* **Acceptance.** `b11` exists on the final pair; the advisor and the critic have read it; the built items it covers are marked walked with their proof, or reopened.
* **Size.** M.

## P0-14 — Gate 1: you try the app on your own phone (owner) — Size S
* **Order.** Needs: P0-13 [d], P5-01 [d], P1-04 [d], P1-10 [d], P1-16 [d], P2-22 [d]. Why: the first of the owner's three thresholds (D-61, decided with the advisor on 2026-11-05): he tries the app alone, on his own phone, before anything is built for a friend. It needs exactly what makes the app worth trying and safe to update: everything above the walk (the next songs prepared, covers offline, Search offline, a download that shows where it is), the walk itself on the release-candidate pair (P0-13) and the release key (without it his first update forces a reinstall and loses his downloads). Nothing else; **no install guide** (the owner installs an app without one; the guide, P5-07, is for his friend).
* **Owner's step.** He only taps. Claude gives him the app with one short instruction in the chat and provides the server it talks to. **Which server is decided when this is close:** if it is his homelab he says yes explicitly (D-59: nothing on his homelab without his word); otherwise a test server Claude runs.
* **What he does.** Installs the app, signs in, uses it as his own player for as long as he likes, and tells Claude what is wrong on the board ("It doesn't work"). Nothing is shared with anybody.
* **Acceptance.** He has the app on his own phone and has used it; what he reported is on the board.
* **Size.** S (his time, not counted in the estimate).

## P0-15 — A plugin that will stop a future Flutter from building (workmanager_android) — Size S
* **Order.** Needs: none. Why: found 6 Nov 2026 while building the release APKs for the proof pass (`handoff-2026-11-03/proof-pass-expected-2026-11-06.md`): every Android build prints "WARNING: Your app uses the following plugins that apply Kotlin Gradle Plugin (KGP): workmanager_android. Future versions of Flutter will fail to build if your app uses plugins that apply KGP." P0-11 moved the build to Built-in Kotlin and removed Flutter's three "will soon be dropped" lines, and this is the next one of the same family. `workmanager` (^0.10.10) is already the newest release, so nothing can be upgraded today. The app uses it in one file, `app/lib/app/background_sync.dart` (a periodic job and a one-off job, both reading alerts), which `P2-12` / ADR-R38 already plan to move to the server.
* **Do.** (1) Keep Flutter pinned (CI and the toolchain note already say 3.47.7), so the warning stays a warning. (2) When `workmanager_android` ships a Built-in Kotlin release, upgrade it (one pull request: `flutter pub upgrade workmanager`, both APKs build, no warning). (3) If the first Flutter release that fails on KGP plugins arrives before that, or if `P2-12` has moved the alert check to the server and the phone only needs a wake-up, replace the plugin with a small native WorkManager channel in `app/android` (about 60 lines), or remove the job. Whichever comes first.
* **Trigger to do it.** Any one of: a Flutter release whose notes say KGP plugins fail to build; a `workmanager_android` release that supports Built-in Kotlin; the pull request that moves the alert check to the server (P2-12), which removes the need anyway. **Reminder:** `flutter build apk` prints the warning every time, so it is seen by every build until this is done.
* **Acceptance.** `flutter build apk --release` prints no KGP-plugin warning; background alerts still arrive (or the job is gone with P2-12 and nothing needs them).
* **Size.** S.
