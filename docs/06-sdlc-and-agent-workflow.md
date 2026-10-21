# 06 — How work is done (SDLC and agent workflow)

## 1. The life of a change

```
idea / bug ─► GitHub Issue (template) ─► triage (planning agent): severity, story (US-xx), acceptance criteria, task file
          ─► implementing agent: branch task/<id>-<slug>, draft PR on first push, small commits, tests with the change
          ─► CI green ─► reviewing agent (never the author) checks the acceptance criteria on a device/VM, comments
          ─► fixes ─► squash-merge to main ─► nightly beta build ─► release when the milestone's exit criteria pass
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
5. Versions: `0.MINOR.PATCH` until 1.0. App `versionCode` = CI build number. Server image tags = the same version.
6. Tags and Releases only from CI (`release.yml`), never from a laptop.
7. Never commit secrets or binaries; `gitleaks` pre-commit hook and CI step; `.gitignore` covers `*.apk`, `*.aab`, `*.env`,
   `*login*.txt`, `*cookies*.txt`, `build/`.

## 3. Tracking

* **GitHub Issues** are the single list of bugs and features (replaces B-, F-, Q-, E- numbers in markdown). Labels: `bug`,
  `feature`, `S1`/`S2`/`S3`, `app`/`server`/`install`/`docs`, `needs-owner`, `blocked`.
* **Project board** columns: Backlog → Ready → In progress → Review → Done.
* Each task file in `tasks/` has an issue; the issue links the task section; the PR closes the issue.
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

## 5. Rules for implementing agents (copy into `AGENTS.md`)

* Read, in order: `docs/README.md`, the task section, the stories it cites, `04` for the area, `07` §1–3. Do not read old docs
  unless the task links one.
* Work only on your task's branch. Do not start other tasks; write new problems you find as issues.
* Tests before or with the code; never weaken a test to make it pass; a skipped test needs an issue number.
* Every user-visible number in the acceptance criteria is **measured and written in the PR** with the setup it was measured on
  (device, network, server, line).
* Plain words on Listener screens; no "Navidrome", "Subsonic", "codec", "kbps", "server address" outside Advanced/Host screens.
* Every tappable widget has a semantics label; every screen works at font scale 2.0 and with 3-button navigation.
* Never print, log, screenshot or commit a password; type passwords with `tools/journeys/typepw.py` (reads a login file, prints
  nothing); never screenshot while a password field is visible.
* Live tests against YouTube are **small** (≤ 10 look-ups per test run), never bursts; never from the owner's machines unless the
  task says so (`§8`).
* When stuck for more than 30 minutes on something outside your task (permissions, a broken tool), stop and write it in the PR.
* At the end: push, mark the PR ready, list in the PR: what changed for a person, evidence, what was not tested and why.

## 6. Documentation rules (so the docs never sprawl again)

* `docs/` describes **the present**. No work logs, no "progress notes", no dated narratives in living docs. History lives in PRs,
  issues, releases and `docs/history/`.
* One topic per file, ≤ ~300 lines; tables over prose; numbers with the setup they were measured on.
* Decisions: one ADR file each in `docs/adr/` (Context → Options → Decision → Why it beats the others → Consequences → Revisit
  when). Superseding an ADR edits its status line and links the new one.
* A doc that disagrees with the code is a bug: fix one of them in the same PR.
* The planning agent owns `docs/product/`, `docs/architecture/` and the roadmap; implementing agents update `docs/guides/` and
  `docs/engineering/` when their change affects them.

## 7. CI (GitHub Actions)

| Workflow | Runs on | Steps |
|----------|---------|-------|
| `app.yml` | PRs touching `app/` or `packages/`; push to `main` | `flutter pub get` → codegen → format check → `dart analyze --fatal-infos` → unit + widget + golden tests (incl. the device-profile matrix of `07` §6) → debug APK build |
| `server.yml` | PRs touching `server/` | ruff + mypy → unit tests → contract tests (API schema) → integration tests against a real Navidrome container → image build (amd64+arm64) |
| `release.yml` | tag `v*` | signed release APK (key from repository secrets) → server images pushed to GHCR → GitHub Release with notes and checksums |
| `docs.yml` | PRs touching `docs/` or `website/` | link check, markdown lint, website build |
| nightly | schedule | emulator journeys (`07` §6) on 2 profiles against a freshly installed server in the runner; yt-dlp update canary (1 look-up) |

## 8. Live environments and safety

| Environment | What it is | May agents change it? |
|-------------|-----------|------------------------|
| CI runners | fresh each run | yes |
| **dev VM** `encore-dev` (192.168.50.133, `ssh encore-dev`) | Encore's own test server on the owner's Proxmox | yes, freely; reinstall from scratch with the installer often |
| **CT 104** `encore` (192.168.50.132) | the old Encore server the owner's phones used | read-only for comparisons; test accounts may play/import; no stack changes without the owner's go |
| Owner's homelab (CT 100–103, host timers, music library, dashboard `:8687`) | separate project | **no** (except what the owner explicitly asks) |
| Emulators `encore_a07`, `encore_friend`, `encore_api36` | test phones | yes, any time (owner's standing permission) |

Live YouTube tests: ≤ 10 look-ups per run, spaced ≥ 2 s; never bursts; stop at the first "confirm you're not a bot" and report it.
The owner's home address is shared by his family and his homelab.
