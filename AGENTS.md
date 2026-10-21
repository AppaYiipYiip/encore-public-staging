# Rules for everyone who changes this repository (people and coding agents)

Read first, in this order: `docs/README.md`, your task in `docs/tasks/`, the stories it cites (`docs/03a-user-stories.md`), the
architecture section it cites (`docs/04-architecture.md`), then `docs/06-sdlc-and-agent-workflow.md` and `docs/07-testing-and-device-matrix.md`
(sections 1 to 3). The plan is in `docs/`; do not rely on anything older.

## Do

* **One task, one branch** (`task/<id>-<slug>`), a **draft PR on the first push**, **small commits** (message: `area: what changed for a person`),
  **push at least every hour**. Squash-merge after CI is green and a second pair of eyes (never the author) has re-run the acceptance
  criteria.
* **Tests with the change.** Never weaken a test to make it pass. A skipped test needs an issue number.
* **Measure what you claim.** Every number in an acceptance criterion is measured and written in the PR with its setup (device, network,
  server, line). "Tests pass" is not "it works": walk the screen like a person (`docs/07` section 10).
* **Plain words** on screens meant for listeners. No "Navidrome", "Subsonic", "codec", "port", "server address" outside Host/Advanced screens.
* **Every tappable widget has a semantics label.** Every screen works at font scale 2.0 and with 3-button navigation.
* Run `tools/check.ps1 -Quick` before every commit (the pre-commit hook does it: `git config core.hooksPath tools/hooks`).

## Don't

* **Never commit** passwords, login files, cookies, `.env`, keys, APK/AAB files. The hook refuses them.
* **Never print, log, screenshot or paste a password.** Type passwords on test devices with `tools/journeys/typepw.py`.
* **Never burst requests at YouTube** (at most 10 look-ups per test run, spaced) and never from a Host's home address unless the task says so.
* Do not start other tasks; file new problems as issues.
* Do not touch the owner's homelab or anything outside this repository's own test machines (`docs/06` section 8).

## Where things are

| | |
|-|-|
| App | `app/` (Flutter project root: run `flutter` commands there) |
| Shared Dart package | `packages/encore_session` |
| Server | `server/legacy/*` today; `server/encore_server` after task P2-01 |
| Checks | `tools/check.ps1` (`-Quick`, `-Server`, `-Live`) |
| Emulator driving | `tools/journeys/ui.py` (never tap blind: `dump` first) |
