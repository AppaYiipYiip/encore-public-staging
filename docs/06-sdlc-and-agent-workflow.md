# 06 — How work is done (SDLC and agent workflow)

## 1. The life of a change

```
idea / bug ─► GitHub Issue (template) ─► triage (planning agent): severity, story (US-xx), acceptance criteria, task file
          ─► implementing agent: branch task/<id>-<slug>, draft PR on first push, small commits, tests with the change
          ─► CI green ─► reviewing agent (never the author) checks the acceptance criteria on a device/VM, comments
          ─► fixes ─► squash-merge to main ─► nightly beta build (planned, not built: section 7) ─► release when the milestone's exit criteria pass
```

* **No feature work without a story** in `03a` (or a new story the planning agent added). This is the brake that was missing (A1).
* **Bug first rule:** an open S1 bug in the area you touch is fixed before new features there.
* **Definition of Ready** (a task may start): story + acceptance criteria with numbers + test plan + files/context listed + dependencies done.
* **Definition of Done** (a task may close): acceptance criteria met *on a device or VM as a person would*, evidence attached to the PR
  (screenshots, timings, logs), tests added (unit + the right level from `07`), docs that describe the present updated, CHANGELOG
  line if a person would notice, CI green, review approved, merged, issue closed.

## 2. Git and GitHub rules

(Also in `05` §5.)
1. Trunk-based: `main` is always releasable. Short-lived branches `task/<task-id>-<slug>`; merge within days, not weeks.
2. Commit small and often; push after each passing local check and **at least every hour**; open a **draft PR on the first push**.
3. Commit message: `area: change in a person's words` (areas: `player`, `search`, `library`, `import`, `offline`, `sync`, `server`,
   `gateway`, `youtube`, `keeper`, `people`, `admin`, `install`, `ci`, `docs`). Body: why, and `Refs #issue`.
4. Squash-merge; the PR title becomes the commit on `main`.
5. Versions: `0.MINOR.PATCH` until 1.0. App `versionCode` = the build number given to `flutter build` with `--build-number` (`pubspec.yaml`'s `+N` when it is left out; D-25, `guides/dev-gotchas.md`); a CI build number once `release.yml` exists. Server image tags = the same version.
6. Tags and Releases only from CI, never from a laptop (`release.yml` is planned, section 7).
7. Never commit secrets or binaries; the pre-commit hook (`tools/hooks/pre-commit`) refuses logins, keys, cookies, environment files and binaries by file name, and CI runs gitleaks (Hygiene `secrets`); `.gitignore` covers `*.apk`, `*.aab`, `*.env`,
   `*login*.txt`, `*cookies*.txt`, `build/`.

## 3. Tracking

* **The roadmap board is the single tracker** (D-60, 2026-11-05; `docs/08-roadmap.md`, `docs/roadmap/README.md`): items (one flat list, Now and Later), notes on an item
  for a problem, a question or a hand-over, claims for who is working on what. GitHub Issues and GitHub Projects are not used for planning: the owner does not use
  GitHub and the board works the same whichever Claude account is signed in. A problem found while working is a note on the item it belongs to, or a new item
  (`python tools/roadmap.py note ITEM "..."`). The old labels and columns were never used and are gone. (The audit rows R-, F- and A- in `history/README.md#audit` keep their
  numbers: they are findings with evidence, not a second list.)
* Each task file in `tasks/` is an item on the board; the pull request that does the work marks it (`python tools/roadmap.py mark ITEM built|walked --evidence "..."`).
* Bug report template (also for agents): **What I did** (steps), **What I expected**, **What happened** (screenshot/log),
  **Device/setup** (phone model, Android version, nav mode, font scale, network, server version, line), **How often**.

## 4. Review: the second pair of eyes

The author never approves its own work. A **reviewing agent** (fresh context) receives: the issue, the task section, the PR diff,
and the evidence. It must:
1. Re-run the acceptance criteria itself on the emulator/VM (not only read the evidence).
2. Walk the touched screens as a person with the checklist in `07` §7 on two device profiles (one small + 3-button nav, one large +
   gesture nav, `07` §4).
3. Check for: swallowed errors (`catch (_) {}`), new jargon on Listener screens, missing semantics labels, unbounded text,
   unhandled offline/slow states, secrets in logs, a test that would pass even if the feature were broken.
4. Approve, or request changes with exact repro steps.

**OPEN (needs owner/advisor):** `tasks/RELEASE-CANDIDATE.md` section 1 holds rules that are not written here, in `AGENTS.md` or in `30`: a row passes only when it was walked on the release-candidate pair; merge only when every check has finished, polled by run id, and confirm `main`'s own run before the next step; freeze `main` once the owner is told a build is ready; advisor checkpoints before a pull request's design, before a merge, before scoring a walk and before telling the owner anything is ready. This section says a reviewing agent is never the author, while that practice is the advisor's go. Decide whether those rules become rules for every change (and are copied into `AGENTS.md`) or stay the release candidate's own.

## 5. Rules for implementing agents (copy into `AGENTS.md`)

* Read, in order: `docs/README.md`, the task section, the stories it cites, `04` for the area, `07` §1–3. Do not read old docs
  unless the task links one.
* Work only on your task's branch. Do not start other tasks; write new problems you find as notes on the board (§3).
* Tests before or with the code; never weaken a test to make it pass; a skipped test names the board item that will un-skip it.
* Every user-visible number in the acceptance criteria is **measured and written in the PR** with the setup it was measured on
  (device, network, server, line).
* Plain words on Listener screens; no "Navidrome", "Subsonic", "codec", "kbps", "server address" outside Advanced/Host screens.
* Every tappable widget has a semantics label; every screen works at font scale 2.0 and with 3-button navigation.
* Never print, log, screenshot or commit a password; type passwords with `python -I tools/journeys/ui.py typefile <login file>` (types only the `password:` line,
  prints nothing); never screenshot while a password field is visible.
* Live tests against YouTube are **small** (≤ 10 look-ups per test run), never bursts; never from the owner's machines unless the
  task says so (`§8`).
* When stuck for more than 30 minutes on something outside your task (permissions, a broken tool), stop and write it in the PR.
* At the end: push, mark the PR ready, list in the PR: what changed for a person, evidence, what was not tested and why.

## 6. Documentation rules (so the docs never sprawl again)

* `docs/` describes **the present**. No work logs, no "progress notes", no dated narratives in living docs. History lives in PRs,
  issues, releases and `docs/history/`.
* One topic per file, ≤ ~300 lines; tables over prose; numbers with the setup they were measured on.
* Decisions: one entry each in the two logs, `10` (the owner's D-xx) and `11` (ADR-Rxx: Context → Options → Decision → Why it beats the others →
  Consequences → Revisit when). Superseding a decision edits its status line and links the new one.
* A doc that disagrees with the code is a bug: fix one of them in the same PR.
* **Decided (the advisor, 5 Nov 2026, when the owner asked for fewer files; `docs/README.md` is the map):** the folders `docs/adr/`, `product/`, `architecture/` and `engineering/` are not made and will not be. Documents keep their numbers, because code, tests and the board cite them (`17`, `31 CN-1`, D-xx, ADR-Rxx); the groups are `tasks/`, `history/`, `evidence/`, `guides/` and `design/`, and `docs/README.md` names every file's kind. The 300-line limit is a goal: `tools/check_docs.py` reports the files over 4,500 words and a dated story inside a truth document.
* The planning agent owns the plan (the board) and the product and architecture documents (`03` to `04`); implementing agents update `docs/guides/` and the
  documents of the area they change, in the same pull request.

## 7. CI (GitHub Actions)

| Workflow (name) | Runs on | Steps |
|-----------------|---------|-------|
| `app.yml` (App) | push to `main` and pull requests touching `app/`, `packages/` or the workflow; by hand | job `verify`: `flutter pub get` → code generation (Drift) → format check → `dart analyze --fatal-infos` → all tests except the `perf` and `live` tags (including the screen pictures; the Linux set is drawn by `goldens.yml`) → the `perf` budgets → the shared package's format, analyze and tests; job `android-debug-build` (only on `main` and by hand, after `verify`): a debug APK |
| `server.yml` (Server) | push to `main` and pull requests touching `server/`, `packages/`, the admin colour files (`tools/gen_admin_tokens.py`, `app/lib/design/tokens.dart`) or the workflow | `encore-server`: ruff, ruff format, mypy, pytest (without the integration tests); `install-scripts`: shellcheck of the installer and `encore`; `encore-server-navidrome`: the integration tests against a real music server and ffmpeg in Docker |
| `server-legacy.yml` (Server legacy) | push to `main` and pull requests touching `server/legacy/` | the five older Python services (unittest) and the Jam hub (Dart analyze and test) |
| `server-image.yml` (Server image) | push to `main` that touches `server/encore_server/`; `v*` tags; weekly (Monday 04:17 UTC); by hand | `tests` (the server's lint, types and tests; skipped for the weekly rebuild), then `image`: build and publish to GitHub's container registry (`:main`, `:<tag>`, `:sha-<commit>`); amd64 only |
| `docs.yml` (Hygiene) | push to `main` and every pull request | `secrets`: gitleaks over the history; `checks`: no logins, keys, cookies, environment files or binaries are tracked, and the untested-rows ratchet (`tools/check_rows.py`, `11` ADR-R41 T2) |
| `goldens.yml` (Goldens (Linux)) | by hand, on the branch that needs the pictures (never `main`) | draws the Linux screen pictures, commits the changed `goldens/linux/*.png` back to that branch (and nothing else) and uploads them as an artifact; App is then started by hand on the new commit (`dev-gotchas.md`, `history/README.md#cloud-resume`) |

**Planned, not built:** `release.yml` (a tag makes the signed APK, the server images and a GitHub Release with checksums; today a `v*` tag only makes `server-image.yml` publish the server image, and the APK is built by hand with the signing key); a documentation link check, markdown lint and website build; a nightly run of the emulator journeys (`07` section 6) and of the yt-dlp canary; arm64 server images.

## 8. Live environments and safety

| Environment | What it is | May agents change it? |
|-------------|-----------|------------------------|
| CI runners | fresh each run | yes |
| **test VM** `encore-install-test` (VM 108 on the owner's Proxmox; log in as `encore` at its LAN address, which the owner's host list shows) | Encore's own test server: the clean-install test by the guide and the QA rounds run here | yes, freely; reinstall from scratch with the installer often |
| *(gone)* | **VM 106 (the old dev VM `encore-dev`), VM 107 and CT 104 were destroyed on 2026-11-03 with their backups**, at the owner's word, after their contents were read and recorded (the owner uses none of the old data). Older documents and evidence files that name them describe what was true when they were written | n/a |
| Owner's homelab (CT 100–103, host timers, music library, dashboard `:8687`) | separate project | **no** (except what the owner explicitly asks) |
| Emulators `encore_a07`, `encore_friend`, `encore_api36` | test phones | yes, any time (owner's standing permission) |

Live YouTube tests: ≤ 10 look-ups per run, spaced ≥ 2 s; never bursts; stop at the first "confirm you're not a bot" and report it.
The owner's home address is shared by his family and his homelab.
