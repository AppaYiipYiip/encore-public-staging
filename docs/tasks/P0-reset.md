# P0 — Reset (no product changes)

Goal: a clean, safe, honest repository and process. Read `../05` first (inventory and target layout).

---

## P0-01 — Secrets out of git, and the rotation list
* **Why.** D1: six `encore-*-login.txt` files and `homelab/CREDENTIALS.md` are committed and on GitHub (`origin/work/eng-review`, 7 files).
* **Context.** Login files are read by `tool/journeys/*.py`, `server/migrate/owner-server/create_admin.ps1`, `RUN-ENCORE-*.bat` (paths
  next to the repo root). `encore-tester-login.txt` was rotated on 2026-10-21 (new password inside; still tracked).
* **Do.**
  1. Create `C:\Users\you\Desktop\encore-workspace\local\logins\` and **move** the six `encore-*-login.txt` files there.
  2. In `old-app/`: `git rm --cached encore-*-login.txt` and commit `chore: login files leave the repository`.
  3. Update every script that reads them to take the path as an argument (default `..\local\logins\<name>`), commit.
  4. Write `local/logins/README.txt` (not in git): what each account is, which server, "never commit".
  5. No password rotation (owner, 2026-10-21: the test passwords are temporary). Do **not** open or copy `homelab/CREDENTIALS.md`.
* **Don't.** Print, cat or grep the contents of any login or credentials file. Rewrite history in `old-app/` (P0-04 makes a new repo instead).
* **Acceptance.** `git ls-files | grep -iE "login|credential"` is empty in `old-app/`; journeys still run with the new paths.
* **Size.** S.

## P0-02 — The homelab folder leaves the repository
* **Why.** D2, owner: "the homelab folder shouldn't be here at all". Encore and the homelab are separate projects.
* **Context.** `old-app/homelab/` (278 files) is byte-identical to `C:\Users\you\Desktop\homelab\` (verified with `diff -rq`
  on 2026-10-21; re-verify before deleting). Also homelab-only: `server/migrate/owner-server/`, `server/portal-patches/`.
* **Do.** Re-run `diff -rq old-app/homelab Desktop/homelab`; if identical, `git rm -r homelab` and commit. Copy
  `server/migrate/owner-server/` and `server/portal-patches/` to `Desktop\homelab\encore-era-scripts\` (the owner's project), then
  `git rm -r` them. Add `homelab/` to `.gitignore`.
* **Don't.** Delete anything on the Desktop copy. Touch the homelab machines.
* **Acceptance.** No `homelab` path, no `owner-server`, no `portal-patches` in `git ls-files`; the Desktop copy unchanged.
* **Size.** S.

## P0-03 — Workspace clutter
* **Why.** D3.
* **Do.** `git -C old-app worktree remove ../baseline-wt` (the commit stays reachable via tag `baseline-8842441`); delete
  `encore-workspace/releases/encore-server.{zip,tar.gz}`; move `old-app/releases/archive/*.apk` and `old-app/releases/*.apk` to
  `encore-workspace/releases-archive/` (keep names), then `git rm -r --cached releases` in `old-app/`.
* **Acceptance.** Workspace contains only `old-app/`, `encore-plan/`, `local/`, `releases-archive/`, `.claude/`, `CLAUDE.md`.
* **Size.** S.

## P0-04 — The new repository (clean tree, new layout, no old-app)
* **Why.** D1, D3, D4, ADR-R1.
* **Context.** Uncommitted work in `old-app/`: `lib/data/server/`, `lib/features/server/`, their tests, `docs/53-app-update-plan.md`,
  and a change in `lib/features/instant/instant_controller.dart`. It generalises the old multi-service "service finder" and is
  **superseded by ADR-R3** (one gateway): commit it in `old-app/` as `wip: service finder (superseded by the reset)` for history and
  do **not** carry it into the new repo. Only 1 of 197 `lib/` paths exists upstream (`main.dart`); everything else is Encore's own.
* **Do.**
  1. In `old-app/`: commit the WIP as above; `git bundle create ../releases-archive/old-repo-2026-10-21.bundle --all`;
     verify with `git bundle verify`.
  2. Create `encore-workspace/encore/` (new folder), `git init -b main`.
  3. Copy files following `../05` §1.2 verdicts into the layout of `../05` §2: `lib`, `test`, `android`, `assets`, `drift_schemas`,
     `pubspec.*`, `analysis_options*.yaml`, `build.yaml`, `dart_test.yaml`, `.metadata`, `.gitattributes` → `app/`;
     `packages/encore_session` → `packages/`; `server/encore-fetch`, `server/encore-people`, `server/encore-admin`,
     `server/reference` → `server/legacy/` (they are moved into `server/encore_server/` in P3-01; `legacy/` is deleted then);
     `tool/` → `tools/`; this plan → `docs/` (rename files into `docs/product`, `docs/architecture`, `docs/engineering`,
     `docs/history`, `docs/adr` as in `../05` §2). `server/encore-quality`, `server/encore-recs`, `server/hub` → `server/legacy/` too
     (phase P4 rebuilds them). Do **not** copy anything marked Delete in `../05` §1.2.
  4. Fix paths broken by the move (`app/` as Flutter root: CI, `tools/check`, hooks, `pack_server_kit.py`).
  5. `git grep -il old-app` must be empty except `docs/history/` (which may mention the history). Rename where found (P0-05 does the
     Android package and icon).
  6. Run the app's full test suite and the server suites from the new layout; all green (or each failure filed and explained).
  7. First commit: `Encore: initial import of the app, server and docs (history in old-repo)`.
* **Don't.** Copy `.git`, build outputs, `.dart_tool`, login files, APKs. Change behaviour.
* **Acceptance.** `gitleaks detect` clean; repo size < 15 MB; tests green; `flutter build apk --debug` works from `app/`.
* **Depends on.** P0-01, P0-02, P0-03. **Size.** M.

## P0-05 — Rename, re-icon, licence
* **Why.** D4, D5; owner: no trace of old-app. Needs D-1 (licence; default GPL-3.0) and D-5 (name; keep "Encore" until decided).
* **Context.** `android/app/build.gradle.kts`: `namespace = "com.example.old-app"`, `applicationId = "app.encore.player"`;
  `MainActivity.kt` and `OldAppApplication.kt` under `kotlin/com/example/old-app/`; launch component today
  `app.encore.player/com.example.old-app.MainActivity`; launcher icons in `android/app/src/main/res/mipmap-*` generated from
  `"old-app Icon.png"` (`flutter_launcher_icons.yaml`); `pubspec.yaml` `name: old-app`, `description: "A new Flutter project."`.
* **Do.** Namespace and Kotlin package → `app.encore.player`; rename `OldAppApplication` → `EncoreApplication`; keep
  `applicationId = app.encore.player` (installed phones keep their data); pubspec `name: encore`, a real description (update all
  `package:old-app/` imports); a new launcher icon (simple temporary mark from the design tokens: green waveform on dark) generated with
  `flutter_launcher_icons`; replace `LICENSE` (GPL-3.0 text), write `README.md` (one sentence, 3 steps, status), empty
  `CHANGELOG.md` with "Unreleased", `SECURITY.md`, a new `PRIVACY.md` (what leaves the phone: nothing except to your own server;
  what leaves the server: song look-ups to YouTube/Deezer/LRCLIB/MusicBrainz).
* **Acceptance.** `git grep -i old-app` empty (outside `docs/history`); the app installs **over** the current build on the emulator
  and keeps the signed-in state (same applicationId, same debug key for now); the launcher shows the new icon.
* **Size.** S–M.

## P0-06 — CI for the app and the server
* **Why.** D7.
* **Do.** `.github/workflows/app.yml`, `server.yml`, `docs.yml` as in `../06` §7 (release.yml comes in P5-01). Flutter version pinned
  (the one in today's `ci.yml`: 3.47.7). Python 3.12; run each legacy server suite (`python -m unittest discover`) until P3-01 replaces them.
  Path filters so app changes don't run server jobs. Cache pub and pip.
* **Acceptance.** A PR that breaks a test is red; the first PR on the new repo is green; run time app ≤ 15 min, server ≤ 10 min.
* **Size.** M.

## P0-07 — GitHub set-up
* **Why.** Owner: "the GitHub is shit, confusing and weird". `../05` §4.
* **Context.** Today: `AppaYiipYiip/encore`, private, default branch `better-audio-player` (stale since 2026-10-16, README emptied),
  branches `master` (old-app upstream) and `work/eng-review` (with passwords), 16 old-app tags, no releases, no description.
* **Do.** (Needs D-8 for pushing.) Rename the old repo to `old-repo`, archive it; create the new `encore` (private), push `main`;
  description, topics; branch protection on `main` (PR + green CI + 1 review, no force push); labels and issue templates
  (`bug.yml` with the fields of `../06` §3, `feature.yml`); a Project board (Backlog/Ready/In progress/Review/Done); one issue per
  task in `tasks/`, linked.
* **Acceptance.** A visitor sees: a README that explains Encore in 30 s, only `main`, no foreign tags, issues and a board that
  match `tasks/`.
* **Depends on.** P0-04, D-8. **Size.** S.

## P0-08 — Files that guide agents
* **Do.** `AGENTS.md` (copy of `../06` §5 + "read `docs/README.md` first"), `CLAUDE.md` with one line pointing to it,
  `.github/pull_request_template.md` (what changed for a person, evidence, setup measured on, not tested + why, checklist from
  `../07` §10), a `gitleaks` pre-commit hook and CI step, `.gitignore` for `*.apk *.aab *.env *login*.txt *cookies*.txt build/`.
* **Acceptance.** Committing a file named `x-login.txt` or containing an API-key-looking string is blocked locally and in CI.
* **Size.** S.

## P0-09 — Environments as code (first part) — Size M
* **Why.** `../24` §2: every test environment rebuildable by one command; real data, legally.
* **Do.** `tools/env/stack up` (server + Navidrome + a seeded library of Creative Commons albums with real tags, covers and lyrics; licences
  listed), `tools/emulators/create A B C D E` and `profile <X>` from configs in the repo, `tools/fixtures/refresh` (recorded outside-service
  answers, ≤ 50 spaced calls). The VM and two-server environments come with P3-07 and P4-09.
* **Acceptance.** A fresh clone runs `tools/env/stack up` and the unit + integration suites against it with no manual step.

## P0-10 — Licence inventory and checks — Size S
* **Why.** `../25`: a public GPL-3.0 project must know every component's licence and every service's terms.
* **Do.** Verify every *verify* row of `../25`; a CI step that lists Dart and Python dependency licences and fails on an unknown or
  incompatible one; `THIRD_PARTY_NOTICES` generation; About → "Open-source licences" in the app.
* **Acceptance.** CI green with the check; the table in `../25` has no *verify* left.
