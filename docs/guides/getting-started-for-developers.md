# Getting started as a developer (read this first)

For a person or a coding agent who has never seen this repository and wants to change something today. It is a map and a first hour, not the
rules: the rules are in `AGENTS.md` and `docs/30-engineering-guide.md`, and this page links to them instead of repeating them. Facts that change
(what is built, what is open) are linked, not copied; the one dated snapshot is the last section.

## 1. What Encore is, in one minute

* A **Flutter Android app** (Riverpod for state, Drift/SQLite for the local library, just_audio for playback) and **one Python server**
  (FastAPI, SQLite) that sits in front of a **Navidrome** music server. People install the server on any spare computer with one script
  (`server/encore_server/deploy/install.sh`); the app signs in to it.
* **Songs are references, not files.** A song is a `song reference` (`sr_…`): metadata plus zero or more files. The app plays a reference
  instantly by asking the server for a signed stream address; the server's *keeper* downloads and stores the songs a person keeps. A better
  file later is just a new file attached to the same reference. (`docs/04-architecture.md`.)
* **Clients are thin.** The app talks only to its own Encore server; the server talks to YouTube and every other outside service, so a
  web or desktop client can exist later (`docs/11-decision-log.md`, ADR-R38). Two calls from the app to outside hosts (Deezer, LRCLIB)
  still exist and are being removed; a test holds them at a baseline that may go down, never up (`app/test/architecture_test.dart`, §6 below).
* **Local first, live second.** The app works offline from its own database; changes go through an outbox to the server; the server pushes
  changes to the person's other devices over one websocket (`/encore/live`). (`docs/17-api-and-sync-contract.md`.)
* YouTube is the weak point and is handled with care: pacing, a rest when YouTube refuses, a canary, and a yt-dlp that updates itself.
  You may never burst requests at it (§7).

## 2. Where things are

| Path | What |
|------|------|
| `app/` | The Flutter project root: run every `flutter` / `dart` command here |
| `packages/encore_session` | Shared Dart package (sign-in session) |
| `server/encore_server/` | The one server (`encore_server/` code, `tests/`, `deploy/` = installer and the `encore` command, `pyproject.toml`) |
| `server/legacy/*` | Older services, tested only when their own folder changes (D-44); do not build on them |
| `tools/` | `check.ps1` (the one command that proves a change), `env.ps1` (toolchain paths), `check_rows.py` (the state-table ratchet), `journeys/` (drive an emulator), `hooks/` (the pre-commit hook) |
| `docs/` | The plan and the source of truth. Start at `docs/README.md` |
| `docs/tasks/` | One file per phase with the task list; `AUDIT.md` lists what is still open; `RELEASE-CANDIDATE.md` says what "passed" means |
| `docs/guides/` | How-tos: this page, `install-test.md` (install on a fresh machine), `dev-gotchas.md` (traps met on this project), `friend.md` |
| `docs/evidence/` | Measurements and walk records, one file each (`c01`…), written when something is proved |
| `.github/workflows/` | `app.yml`, `server.yml`, `docs.yml`, `goldens.yml`, `server-image.yml` (builds and publishes the server image) |

## 3. What you need

The project is developed on Windows with PowerShell 5.1; CI runs on Linux. `tools/env.ps1` puts the toolchain on the path (it expects
`C:\dev\flutter`, `C:\dev\jdk`, `C:\dev\android-sdk`; change the paths if yours differ).

| Tool | Version | Why |
|------|---------|-----|
| Flutter | 3.47.7 (the version CI uses; `flutter-version` in `.github/workflows/app.yml`) | the app |
| JDK | 17 or newer (CI uses 17) | the Android build |
| Android SDK + an emulator | any recent API level; the project's emulators are named in `docs/06` §8 | running the app |
| Python | 3.12 or newer | the server |
| Docker | any recent | the integration tests and a real install |
| `gh` (GitHub CLI) | recent | PRs, and the installer's sign-in while the image is private |

The repository and the server image are **private** for now (decision D-49): you need a GitHub login that can read them.

## 4. Your first hour

```powershell
git clone https://github.com/AppaYiipYiip/encore.git ; cd encore
git config core.hooksPath tools/hooks          # the pre-commit hook runs the quick gate on code commits
. .\tools\env.ps1                              # toolchain on the path (dot-source it)

# the app and the shared package: generate code, format, analyze, every test
.\tools\check.ps1                              # first run (a few minutes); later: .\tools\check.ps1 -Quick

# the server (from server/encore_server)
cd server\encore_server
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[youtube,dev]"
ruff check . ; ruff format --check . ; mypy encore_server ; pytest      # exactly what CI runs
```

* The Drift code (`app_database.g.dart`) is not committed: `check.ps1` generates it (`dart run build_runner build --delete-conflicting-outputs`).
* `pytest` is configured with `pythonpath = ["."]` so it works from any folder; the tests use fakes and do not need Docker or the internet.
  The integration suite does need Docker: `docker compose -f tests/integration/compose.yaml up --build --abort-on-container-exit --exit-code-from tests`.
* **Golden (screen picture) files are only ever updated by the `goldens` workflow**, never from a developer's machine: the pictures differ
  between Windows and Linux. See `docs/guides/dev-gotchas.md`.
* To see the whole thing as a user does, install the server on a spare machine or VM by `docs/guides/install-test.md` (about 10 minutes) and
  point the app (emulator or phone) at the address the installer prints. `server/encore_server/compose.dev.yaml` is older: its header describes
  the setup of the first weeks, so check it before relying on it.

## 5. How a change goes (the short version of `docs/06` and `AGENTS.md`)

1. **Find the task** in `docs/tasks/` (open items: `AUDIT.md`). One task, one branch: `task/<id>-<slug>` (docs-only changes: `docs/<slug>`).
2. **Answer the ten questions** in `docs/30-engineering-guide.md` §0 before writing code. If you cannot, stop and ask.
3. **Test first, with the change.** Never weaken a test to make it pass; a skipped test needs an issue number. For a bug fix, make the
   test fail on the old code first (the project checks its own tests this way: break the code on purpose and see the test go red).
4. **Small commits**, message `area: what changed for a person`. Push at least every hour. Open a **draft PR on the first push**.
5. **CI** must be green on the PR: the job names are in the workflows; wait for every check and poll them by run id, do not assume.
6. **Merge** by squash, pinned to the head commit you reviewed (`gh pr merge N --squash --match-head-commit <sha>`), never with `--admin`,
   and only after a second pair of eyes (never the author) has re-run the acceptance criteria. After the merge, `main`'s own run must be
   green before the next step.
7. **"Passed" has a strict meaning**: a row of the plan passes only when walked as a person on the release-candidate pair (the published
   image and the app built from the same commit, on a clean machine, to the end state). Until then the word is **"built, not walked"**
   (`docs/tasks/RELEASE-CANDIDATE.md` §1). Use that vocabulary in PRs.

## 6. Where the truth lives, and how not to be misled

* **Current state and what is next:** `python tools/roadmap.py brief --role agent` (the board); `docs/README.md` is the map of every document. **Decisions waiting for the owner:** `docs/10`.
  **Decisions made and why, with the options compared:** `docs/11` (ADR-R1…). Older documents (anything before the 2026-10-21 reset) are
  history: read one only when a task links it.
* **The state tables `docs/31`-`34`** (ways to join and play, states, failures, conflicts) are enforced by `tools/check_rows.py`: a "Built"
  row must name a test or list one that exists. **Rule: when you touch a state, update its row.**
* **Ratchets** (`docs/30` §5): a rule with a *baseline* of known violations. A new violation fails the test; a baseline entry that has been
  fixed also fails until you delete it from the baseline, so it cannot creep back. The goal of every baseline is empty. The app's rules,
  including "no client calls an outside host" (two known calls today: Deezer and LRCLIB), are in `app/test/architecture_test.dart`.
* **Ids repeat across documents; always read an id together with its file name.** `D-n` = a decision for the owner (`docs/10`); `ADR-Rn` =
  a decision taken (`docs/11`); `P<phase>-nn` = a task (`docs/tasks/P*.md`); `F<n>` = findings from the owner's field tests and the catalogue
  (`docs/tasks/AUDIT.md`); **`B<n>` means three different things**: a finding in `docs/01`, a check row in `docs/tasks/RELEASE-CANDIDATE.md`
  (B0-B6), and a backend bug in `docs/history/reviews-2026-10-31.md#qa-backend-2026-10-31` (B1-B12); `c0n` = an evidence file in `docs/evidence/`; `b11` = the
  walk record of the release-candidate pair (it does not exist yet); `A-n` = a finding of the 3 Nov 2026 audit of `main` (named in PR
  titles; the full list is in the owner's project book, which is kept outside the repository, so ask).
* **A doc can promise what the code does not do.** An audit on 3 Nov 2026 found several (the API inventory, "never run" sentences, states
  marked built without a test). If a document and the code disagree, the code is the fact: fix the document in the same PR and say so.
* **Plain words on screens meant for listeners** (no "Navidrome", "Subsonic", "codec", "port"). Every tappable widget has a semantics
  label; every screen works at font scale 2.0 and with 3-button navigation.

## 7. Safety rules (these have been broken before)

* **Never print, log, paste or screenshot a password or a token.** Never commit a login file, `.env`, key or APK. The hook refuses them.
  On a test device, type passwords with `python -I tools/journeys/ui.py typefile <login file>`.
* **YouTube:** at most 10 look-ups per test run, spaced at least 2 seconds; stop at the first "confirm you are not a bot". The owner's home
  address was refused once for a day. Do not point a loop at it.
* **No outside calls from a client** (YouTube, Deezer, lyrics, covers): the server does that (ADR-R38).
* **Do not touch the owner's homelab or anything outside this repository's own test machine** (`docs/06` §8). Remote machines that run
  Encore for real people are changed only with the owner's word, and a backup comes first (`encore backup`).
* **Ask the strongest model you have** before a hard-to-undo choice and again before calling a multi-step task done (`docs/30` §3).

## 8. Snapshot, 3 November 2026 (will go stale; the live version is `docs/README.md` and `docs/tasks/AUDIT.md`)

* The server and the app are built; an install by the guide on a bare VM took 9 min 51 s (`docs/evidence/c06`). The release-candidate pair
  (app build 125 and the server image from the same server code) is **built, not walked**: QA rounds 2 and 3 and the walk record `b11` are
  next, and nothing goes to the owner until `b11` exists and has been read.
* Open and held: lyrics on the server (P2-14, branch and draft PR, held until `b11`); the catalogue move to the server (P2-12) and moving
  Deezer and LRCLIB off the app (D-51, ratchet 2 to 0); the pairing link and QR (P2-19); the quality tier (P4-04, off by default, brings its
  own containers); a public image so the installer needs no GitHub sign-in.
* Not proved yet: a phone on mobile data through the Funnel, the live connection for two hours through it (X-7), a real update to a newer
  image, and ARM computers.

## 9. When you are stuck

Read `docs/guides/dev-gotchas.md` first (Windows and PowerShell 5.1 traps, building and testing, goldens, driving the emulator, Docker on
Linux hosts, Navidrome facts that surprised us). Then `docs/30` §2 ("if you see this in a diff, stop"). Then ask: file an issue with what you
saw, what you expected, and the command you ran.
