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

## 2. Target layout (the new repository `encore`)

```
encore/                          one repository, one product
├─ README.md                     what Encore is, screenshots, install in 3 steps, links to docs
├─ LICENSE                       GPL-3.0 (owner decision D-1)
├─ AGENTS.md                     rules for coding agents (copy of 06 §5, short); CLAUDE.md = one line pointing to it
├─ CHANGELOG.md                  one line per user-visible change, per release
├─ SECURITY.md                   how to report a vulnerability
├─ app/                          the Android app (Flutter project root)
│  ├─ lib/ … (app, core, data, domain, features, playback, design)
│  ├─ test/                      unit + widget + golden tests
│  ├─ integration_test/          on-device journeys (07 §6)
│  ├─ android/                   package app.encore.player, namespace app.encore.player
│  ├─ assets/  drift_schemas/  pubspec.yaml  analysis_options.yaml …
├─ packages/
│  └─ encore_session/            shared Dart (Jam, later)
├─ server/
│  ├─ encore_server/             ONE Python package: gateway, accounts, library, playback, live, catalogue,
│  │                             sources/youtube, keeper, imports, people, admin (04 §2)
│  ├─ admin_web/                 the admin/setup web app (built into the image)
│  ├─ tests/                     unit, contract (API), integration (real Navidrome in Docker)
│  ├─ deploy/                    compose.yaml, .env.example, install.sh, encore (CLI), tailscale/serve.json
│  ├─ Dockerfile  pyproject.toml
├─ website/                      the public site: landing, guide, downloads (static; built from docs/guides)
├─ docs/
│  ├─ README.md                  index (this plan's README, adapted)
│  ├─ product/                   03, 03a
│  ├─ architecture/              04 + diagrams
│  ├─ adr/                       0001-*.md … (one file per decision; ADR-R1… from 11 become 0001…)
│  ├─ engineering/               06 SDLC, 07 testing, dev setup, release
│  ├─ guides/                    install, away-from-home, troubleshooting, for-friends (source of the website)
│  └─ history/                   01, 02, 09 of this plan (why we reset); old docs are NOT copied
├─ tools/                        dev scripts: journeys (adb walk), perf, kit
└─ .github/
   ├─ workflows/ app.yml  server.yml  release.yml  docs.yml
   ├─ ISSUE_TEMPLATE/ bug.yml  feature.yml
   └─ pull_request_template.md
```

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
4. **Before committing**, run the quick check (`tools/check --quick`: format, analyze, unit tests of the touched area); CI runs the rest.
5. **Never commit**: passwords, login files, cookies, `.env`, APK/AAB/zip files, build folders. A pre-commit secret scan
   (`gitleaks`) blocks them.
6. **The owner must allow pushing once**: add to `~/.claude/settings.json` → `permissions.allow`: `"Bash(git push:*)"` and
   `"Bash(gh pr create:*)"`, `"Bash(gh pr ready:*)"`, `"Bash(gh pr merge:*)"`. Agents cannot change their own permissions
   (owner decision D-8). Until then, agents commit locally and the final message of every task says "not pushed: permission".
