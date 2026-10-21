# 05 — Repository, folders and GitHub

Owner (2026-10-21): "the files and folders here are messy … the homelab folder shouldn't be here at all … the GitHub is shit,
confusing and weird". This page lists what exists, what each thing becomes, the target layout, and how GitHub must look.
The work itself is tasks **P0-01 … P0-08** in [`tasks/P0-reset.md`](tasks/P0-reset.md).

## 1. What exists today (2026-10-21)

### 1.1 The workspace folder `C:\Users\you\Desktop\encore-workspace\`

| Item | What it is | Becomes |
|------|-----------|---------|
| `old-app/` | The git repository (branch `work/eng-review`, 46 commits not on GitHub, uncommitted app work: `lib/data/server/`, `lib/features/server/`, tests, `docs/53`, a change to `instant_controller.dart`) | Source for the **new** repository `encore/` (P0-04); then kept read-only as `archive/old-repo/` until the new one is proven, then deleted (owner's go) |
| `baseline-wt/` | A git worktree of the old baseline commit `8842441` (detached) | Remove with `git worktree remove` (recoverable from the tag) |
| `releases/encore-server.{zip,tar.gz}` | An old packed server kit (2026-10-17) | Delete (superseded; future kits are GitHub Release assets) |
| `.claude/settings.local.json` | Claude Code project settings | Keep (owner's) |
| `encore-plan/` | This plan | Becomes `docs/` of the new repo (P0-04) |
| `CLAUDE.md` | Pointer for agents (written by the planning agent) | Keep at the workspace level; a repo-level `AGENTS.md`/`CLAUDE.md` is added in P0-04 |

### 1.2 Inside the repository (tracked files per top-level item)

| Item | Tracked files | What it is | Verdict |
|------|--------------:|-----------|---------|
| `lib/` | 197 | The Encore app (rewritten; 1 path left from old-app: `main.dart`) | **Keep** → `app/lib/` |
| `test/` | 166 | App tests | **Keep** → `app/test/` |
| `android/` | 95 | Android project; `namespace com.example.old-app`, `OldAppApplication.kt`, old-app launcher icons in `res/mipmap-*` (from `flutter_launcher_icons.yaml` → `"old-app Icon.png"`) | **Keep, rename and re-icon** → `app/android/` (P0-05) |
| `assets/` | 6 | Figtree fonts + OFL licence | **Keep** → `app/assets/` |
| `drift_schemas/` | 5 | Database schema history (needed for migrations) | **Keep** → `app/drift_schemas/` |
| `packages/encore_session/` | 12 | Jam engine shared by app and hub | **Keep** → `packages/encore_session/` (dormant until Jam returns) |
| `packages/flutter_chrome_cast/` | 167 | old-app's vendored Chromecast plugin; **not referenced** by `pubspec.yaml` or `lib/` | **Delete** |
| `server/encore-fetch, -people, -admin` | ~110 | Python services | **Move into the new single server** `server/encore_server/` modules (P3-01); old folders deleted after the move |
| `server/encore-quality, encore-recs, hub` | ~60 | Quality tier, recommendations, Jam hub | **Keep** → `server/legacy/`; rebuilt as modules in phase P4 (owner: everything in the first version) |
| `server/reference/` | ~30 | Compose kit, `setup.sh`, `encore_user.py`, checks, VM test scripts | **Rework** → `server/deploy/` (compose, install script, `encore` CLI) + `server/tests/` |
| `server/migrate/owner-server/` | 10 | Scripts for the owner's homelab containers | **Delete from the product** (homelab-specific); copy to the owner's homelab folder if he wants them |
| `server/portal-patches/` | 1 | Patch for the owner's private request portal | **Delete** (homelab) |
| `tool/` | 28 | Check script, hooks, journeys, profiling, kit packer | **Keep, tidy** → `tools/` (one folder); journeys get the new test harness (`07`) |
| `tools/`, `packaging/` | 2 | old-app's macOS DMG background generator | **Delete** |
| `docs/` | 101 | 60 old documents + resource samples | **Archive**: move to `docs/archive/2026-10/` in the old repo only; the new repo starts with this plan as `docs/` |
| `homelab/` | 270 | The owner's homelab notes, scripts **and `CREDENTIALS.md`** (identical copy at `Desktop\homelab`, verified) | **Delete from the repo**; never in the new one |
| `legacy_archive/` | 260 | old-app's old UI and workflows "kept for reference" | **Delete** |
| `releases/` | 51 | **50 APK files committed into git** (the main reason `.git` is 238 MB) + README | **Delete from git**; APKs go to **GitHub Releases** (P0-07); the local archive stays outside the repo (`..\releases-archive\`) |
| `react-website/`, `fastlane/`, `screenshots/`, `old-app-promo.gif`, `CNAME`, `.htaccess`, `_headers`, `.well-known/` | ~90 | old-app's website, store listings, promo | **Delete** (the Encore website is a new `website/`, P5-05) |
| `ios/`, `macos/`, `windows/`, `linux/`, `web/`, `tizen/` | ~170 | Other platforms from old-app | **Delete** (Android only for v1; Flutter regenerates platform folders when iOS/web/desktop start: `flutter create --platforms=web .`) |
| `README.md`, `CHANGELOG.md`, `PRIVACY_POLICY.md`, `CREDITS.md`, `LICENSE` | 5 | **old-app's** README, changelog, privacy policy, credits, CC BY-NC-SA licence | **Replace** with Encore's (P0-04, P0-05) |
| `.github/ISSUE_TEMPLATE/*`, `.github/workflows/ci.yml` | 3 | old-app's issue forms; CI on the wrong branch | **Replace** (P0-06) |
| `encore-*-login.txt` (6), `APPLY-CLAUDE-AUTONOMY.bat`, `RUN-ENCORE-*.bat` (3), `claude-*.PROPOSED.json` (2), `HOW-TO-GIVE-CLAUDE-AUTONOMY.md` | 13 | **Passwords** and one-off helpers for the owner | **Out of git.** Login files → `..\local\logins\` (never committed); helpers deleted (their steps are done) |
| `Gemfile`, `installer.nsi`, `Dockerfile.release`, `build_release.ps1`, `build-release-apk.sh`, `run_with_env.ps1`, `analysis_report.txt`, `devtools_options.yaml`, `crowdin.yml`, `l10n.yaml` | ~10 | old-app build/release/translation helpers | **Delete** (CI builds releases, P0-06/P5-01) |
| `pubspec.yaml`, `pubspec.lock`, `analysis_options*.yaml`, `build.yaml`, `dart_test.yaml`, `.metadata`, `.gitattributes`, `.gitignore`, `.vscode/` | | Flutter project files | **Keep** → `app/` (rename `name: old-app` → `encore`, real description) |
| `offline_music/`, `libCachedImageData/`, `build/`, `.dart_tool/` | 0 | Untracked local folders created by builds/runs | Ignore (`.gitignore`) |

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
| Clean in place (delete folders, rename, new commits) | Keeps history and blame | Passwords, 50 APKs, old-app's 900+ commits and tags stay in history forever; repo stays 238 MB; still a "fork" | Rejected |
| Rewrite history in place (`git filter-repo`) | Keeps Encore's own commits, removes secrets/binaries | Complex; every clone breaks; old-app history is intertwined with the first commits; easy to miss a secret | Rejected |
| **New repository, one initial commit from the cleaned tree, old repo archived then deleted** | No secrets, no old-app, no binaries, small; a clear `main`; the owner's wish "drop anything old-app" is met exactly | Loses line-level history of the last 5 days (kept in the archived old repo and a `git bundle` until the owner deletes it) | **Chosen** |

## 4. How GitHub must look (P0-07)

* **Repository** `AppaYiipYiip/encore` → the *old* one is renamed `old-repo` (private, archived) after the new one is pushed; the new
  one takes the name `encore`. Delete `old-repo` only when the owner says so (no password rotation needed: owner, 2026-10-21).
* **Default branch `main`.** No `master`, no `better-audio-player`, no long-lived `work/*` branches.
* **Description, topics** (`music`, `self-hosted`, `navidrome`, `android`, `flutter`), website link.
* **README** that a stranger understands in 30 s: one sentence, three screenshots, "Install in 3 steps", status badge, links.
* **Releases** (not files in git): `vX.Y.Z` with the APK (signed with the release key), the server image tag, release notes in plain
  words. Pre-releases `vX.Y.Z-beta.N` for testers.
* **Tags** only Encore's: `v0.2.0` … (semantic versioning). No old-app tags.
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
