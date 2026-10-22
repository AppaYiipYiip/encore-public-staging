# P0 — Reset (no product changes)

Goal: a clean, safe, honest repository and process. Read `../05` first (where it started, and the target layout).

---

## P0-01 to P0-05 — done (kept as a record)

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
* **Why.** D7.
* **Do.** `.github/workflows/app.yml`, `server.yml`, `docs.yml` as in `../06` §7 (release.yml comes in P5-01). Flutter version pinned
  (the one in today's `ci.yml`: 3.47.7). Python 3.12; run each legacy server suite (`python -m unittest discover`) until P3-01 replaces them.
  Path filters so app changes don't run server jobs. Cache pub and pip.
* **Acceptance.** A PR that breaks a test is red; the first PR on the new repo is green; run time app ≤ 15 min, server ≤ 10 min.
* **Size.** M.

## P0-07 — GitHub set-up
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
