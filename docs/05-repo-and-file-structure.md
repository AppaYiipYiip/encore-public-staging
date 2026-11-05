# 05 — Repository, folders and GitHub

Owner (2026-10-21): "the files and folders here are messy … the homelab folder shouldn't be here at all … the GitHub is shit,
confusing and weird". This page lists what exists, what each thing becomes, the target layout, and how GitHub must look.
The work itself was tasks **P0-01 … P0-08** in [`tasks/P0-reset.md`](tasks/P0-reset.md).

## 1. Where it started (2026-10-21)

The first five days of work lived in another repository: a fork of an existing player, with the owner's homelab folder, six committed
login files, 50 APK files (the reason `.git` was 238 MB), a vendored plugin and platform folders nothing used, a website, store
listings, the fork's own licence (CC BY-NC-SA 4.0), name and 900+ upstream commits. P0-04 made this repository from a cleaned tree.

| Carried over | Became |
|--------------|--------|
| The Flutter app: `lib/`, `test/`, `android/`, `assets/`, `drift_schemas/`, `pubspec.*`, the analysis files | `app/` (Android package `app.encore.player`) |
| `packages/encore_session/` (Jam engine) | `packages/encore_session/` (dormant until Jam returns) |
| The Python services (fetch, people, admin, quality, recs, hub, the reference kit) | `server/legacy/`, moved into `server/encore_server/` module by module (P2, P3, P4) |
| The check script, hooks, journeys, profiling scripts | `tools/` |
| The plan | `docs/` |

| Left behind (never copied) | Why |
|----------------------------|-----|
| The owner's homelab notes and scripts, one of them `CREDENTIALS.md` | A separate project; an identical copy lives in `Desktop\homelab` |
| `encore-*-login.txt` and one-off helper scripts | Passwords never enter git; logins live in `..\local\logins\` |
| 50 APK files | APKs go to GitHub Releases; local copies are in `..\releases-archive\` |
| A vendored Chromecast plugin, the other platforms (iOS, macOS, Windows, Linux, web, Tizen), the old UI "kept for reference", the website, store listings, promo, translation and release helpers | Not used by an Android-only first version |
| The old README, changelog, privacy policy, credits and licence | Replaced by Encore's own (GPL-3.0) |
| The 60 old documents | History; they exist only in the archive bundle |

The old repository's full history is `..\releases-archive\old-repo-2026-10-22.bundle` (checked with `git bundle verify`); its
uncommitted service-finder work, which the reset superseded, sits next to it in two `wip-` files. The old working folder itself was
deleted on 2026-10-22 (owner: "we are no longer related to that project").

## 2. The layout (checked against the repository on 2026-11-01; what is only planned is marked)

```
encore/                          one repository, one product
├─ README.md  LICENSE  CHANGELOG.md  SECURITY.md  PRIVACY.md
├─ AGENTS.md                     rules for coding agents; CLAUDE.md = one line pointing to it
├─ app/                          the Android app (Flutter project root)
│  ├─ lib/                       app, core, data, design, domain, features, playback
│  ├─ test/                      unit, widget and golden tests (features/goldens/windows and /linux), architecture_test.dart
│  ├─ android/                   package app.encore.player, namespace app.encore.player
│  ├─ assets/  drift_schemas/  pubspec.yaml  analysis_options.yaml  analysis_options_strict.yaml  build.yaml  dart_test.yaml
├─ packages/
│  └─ encore_session/            shared Dart (Jam engine, dormant until Jam returns)
├─ server/
│  ├─ encore_server/             the Encore server
│  │  ├─ encore_server/          ONE Python package: gateway, accounts, library, playback, live, sources/youtube, keeper, imports,
│  │  │                          scanner, scheduler, notifications, migrations/ (04 §2)
│  │  ├─ tests/                  unit, contract (API) and tests/integration (a real Navidrome in Docker)
│  │  ├─ deploy/                 compose.yaml, install.sh, encore (the CLI)
│  │  ├─ Dockerfile  entrypoint.sh  compose.dev.yaml  pyproject.toml
│  └─ legacy/                    the earlier Python services and the Jam hub, moved into encore_server module by module (P2, P3, P4)
├─ docs/                         the numbered documents 01 to 34 and README.md (the plan)
│  ├─ tasks/                     task files, QA and audit logs, CLOUD-RESUME
│  ├─ design/                    screen inventory, directions and reviews (HTML and markdown)
│  ├─ evidence/                  walks, measurements, drawings of what was seen
│  └─ guides/                    install-test, friend, dev-gotchas
├─ tools/                        check.ps1 (the one command), check_rows.py, hooks/, journeys/ (the adb walk), profile/, vmprobe/, benches
└─ .github/
   ├─ workflows/ app.yml  server.yml  server-legacy.yml  server-image.yml  docs.yml  goldens.yml
   ├─ ISSUE_TEMPLATE/ bug.yml  feature.yml
   └─ pull_request_template.md
```

**Planned and not made:** `website/` (the public site, built from `docs/guides`, P5), an admin and setup web app for the image (04 §2), `app/integration_test/` (on-device journeys, 07 §6; today they are scripts in `tools/journeys`), and the split of `docs/` into `product/`, `architecture/`, `adr/`, `engineering/` and `history/` (see the OPEN line in `06` §6).

**Outside the repository, never committed:**
```
encore-workspace\            (rename later to "encore-workspace" if the owner wants)
├─ encore\                       the repository
├─ local\logins\                 encore-*-login.txt (test accounts; .gitignore'd by location)
├─ releases-archive\             APKs by build/commit (copied from the old repo)
└─ CLAUDE.md                     pointer for agents
Desktop\homelab\                 the owner's homelab project (separate, already there)
```

## 3. Why a new repository instead of cleaning the old one

| Option | For | Against | Verdict |
|--------|-----|---------|---------|
| Clean in place (delete folders, rename, new commits) | Keeps history and blame | Passwords, 50 APKs, the upstream project's 900+ commits and tags stay in history forever; repo stays 238 MB; still a "fork" | Rejected |
| Rewrite history in place (`git filter-repo`) | Keeps Encore's own commits, removes secrets/binaries | Complex; every clone breaks; The upstream history is intertwined with the first commits; easy to miss a secret | Rejected |
| **New repository, one initial commit from the cleaned tree, old repo archived then deleted** | No secrets, no upstream history, no binaries, small; a clear `main`; the owner's wish "drop anything from the old project" is met exactly | Loses line-level history of the last 5 days (kept in the archived old repo and a `git bundle` until the owner deletes it) | **Chosen** |

## 4. How GitHub must look (P0-07)

* **Repository** `AppaYiipYiip/encore` → the *old* one is renamed `old-repo` (private, archived) after the new one is pushed; the new
  one takes the name `encore`. Delete `old-repo` only when the owner says so (no password rotation needed: owner, 2026-10-21).
* **Default branch `main`.** No `master`, no `better-audio-player`, no long-lived `work/*` branches.
* **Description, topics** (`music`, `self-hosted`, `navidrome`, `android`, `flutter`), website link.
* **README** that a stranger understands in 30 s: one sentence, three screenshots, "Install in 3 steps", status badge, links.
* **Releases** (not files in git): `vX.Y.Z` with the APK (signed with the release key), the server image tag, release notes in plain
  words. Pre-releases `vX.Y.Z-beta.N` for testers.
* **Tags** only Encore's: `v0.2.0` … (semantic versioning). No upstream tags.
* **Branch protection on `main`**: PR required, CI green required, 1 approving review (the reviewing agent or the owner), no force push.
* **Issues** as the only bug/feature tracker, with labels: `bug`, `S1`/`S2`/`S3`, `app`, `server`, `docs`, `good-first-task`;
  a Project board: Backlog → Ready → In progress → Review → Done.
* **Packages**: server images on `ghcr.io/appayiipyiip/encore-server` (multi-arch), public when the repo goes public.
* **Visibility**: private until P4 (public release) is done; then public (GPL-3.0).

## 5. Committing and pushing often (owner, 2026-10-21: "commit to github much more often")

The old work sat **46 commits on one laptop** because pushes were blocked by Claude Code's permission settings and nobody fixed it.
Rules (also in `06` §2):

1. **Small commits, often**: commit every time a test turns green or a coherent step is finished (typically every 15–45 minutes of
   work). One idea per commit. Message: `area: what changed for a person` (e.g. `player: tapping a song while offline no longer
   skips through the playlist`).
2. **Push at least**: after every commit that passes the local quick check, at the end of every task, and **never later than one
   hour** after the last push. A day's work never exists only on one machine.
3. **One branch per task** (`task/P1-01-lean-resolver`), opened as a **draft PR on the first push** so progress is visible; marked
   ready when acceptance criteria are met; squash-merged into `main` after CI and review.
4. **Before committing**, run the quick check (`tools/check.ps1 -Quick`: format, analyze, unit tests of the touched area); CI runs the rest.
5. **Never commit**: passwords, login files, cookies, `.env`, APK/AAB/zip files, build folders. The pre-commit hook blocks them
   by file name, and CI scans for secrets with gitleaks.
6. **Pushing is allowed** (done: agents push branches, open pull requests and merge them with `gh`, each a squash merge on the checked head). Agents cannot change their own permissions (owner decision D-8): if a push is ever refused, the final message of the task says "not pushed: permission" and the owner is asked once.
