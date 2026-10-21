# 24 — Seeing what happens, and test environments as code

Why: agents (and the owner) must be able to see *why* something failed on a phone or a server without guessing, and every test
environment must be rebuildable by one command. Today: logs differ per service, nothing links a phone action to the server lines it
caused, the emulator setup lives in memory notes, and the only test servers are hand-made.

## 1. One request, followed end to end

* Every app request carries `X-Request-Id` (ULID) and `X-Device-Id`; the server logs them in **structured JSON lines**
  (`time, level, module, request_id, device, person_id, event, ms, error_code`), never titles, passwords, tokens or signed URLs (`21` §2).
* The app keeps a **ring buffer** of its last 2,000 log lines (same request ids, perf spans like `play.audible`, errors) on the phone.
* **Debug bundle:** Settings → About → "Report a problem" (opt-in per report) sends the phone's ring buffer + device facts (model,
  Android version, navigation mode, font scale, app version, network type) to the Host's server, which attaches its own log lines for
  the same request ids and time window. Admin → Problems → "Download for a bug report" gives one zip to attach to a GitHub issue.
  (Extends P4-13; build the request ids and the ring buffer already in P1-06.)
* Server stage timings (`search`, `extract`, `first_byte`, `proxy`, `keep`, `scan`) are logged for every work item; `encore stats`
  prints p50/p95 of the last day per stage.

## 2. Test environments, one command each (in `tools/env/`)

| Environment | Command | What it is |
|-------------|---------|------------|
| **Local stack** | `tools/env/stack up` | Encore server + Navidrome in Docker on any dev machine, with a seeded library of **freely licensed real music** (e.g. Creative Commons albums with real tags, covers and lyrics; licences listed in the repo) so tests use real files that may legally live in the repository's test assets |
| **Fresh VM** | `tools/env/vm new --os ubuntu-26.04 [--arm64] [--slow]` | a new VM on the dev Proxmox via cloud-init, the website's install command run on it, the setup wizard completed by a script; `--slow` shapes the line to 10/1 Mbit/s and 2 vCPU (the SLOW profile, `07` §2) |
| **Two servers** | `tools/env/federation up` | two stacks that can federate on a private network with a dev-only "trust this test certificate" flag, so federation tests need no public address (never enabled in releases) |
| **Emulators** | `tools/emulators/create A B C D E` | the AVDs of `07` §4 created from configs in the repo; `tools/emulators/profile C` applies navigation mode, font scale, size, locale; resets afterwards |
| **CI emulator** | GitHub Actions on Linux with KVM (android-emulator-runner) | the nightly journeys on profiles A and B against a fresh local stack |

Accounts on test servers are always made **through the real flows** (setup wizard, invitations) by scripts, never inserted into
databases (owner's rule: real data). Login files go to `../local/logins/` (never in git).

## 3. Recorded answers from outside services

YouTube Music, Deezer, MusicBrainz and LRCLIB answers used by tests are **recorded** (fixtures) by `tools/fixtures/refresh` (≤ 50
calls, spaced, run monthly or when a test needs new ones) and replayed in CI; one nightly **live canary** (≤ 3 look-ups) tells whether
the recordings still match reality (`07` §6).

## 4. Switches for risky features

The server's `info.features` carries switches the Host or a release can flip without an app update: YouTube source, federation,
quality tier, smart shuffle, new player code paths. A broken feature can be turned off for everyone the same day (a kill switch), and a
new one tried by the owner first (per-person beta flag).

## 5. What an agent needs on day one (put in `AGENTS.md`)

* `tools/check --quick` / `--full`; `tools/env/stack up`; `tools/emulators/create`; `tools/journeys/ui.py` (drive the emulator by
  labels), `typepw.py` (passwords, never printed), `play_timing.py` (measure tap → audible); where the debug bundles are.
* The rule: a bug report or a fix without request ids, setup and numbers is incomplete.
