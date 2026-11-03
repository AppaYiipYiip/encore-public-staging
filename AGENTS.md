# Rules for everyone who changes this repository (people and coding agents)

Read first, in this order: `docs/README.md`, your task in `docs/tasks/`, the stories it cites (`docs/03a-user-stories.md`), the
architecture section it cites (`docs/04-architecture.md`), then `docs/06-sdlc-and-agent-workflow.md` and `docs/07-testing-and-device-matrix.md`
(sections 1 to 3), and **`docs/30-engineering-guide.md`** (what to do, what not to do, and which rules a machine checks). The plan is in `docs/`; do not rely on anything older.
If you start with no memory of earlier work: `docs/README.md` has the current state and what is next; `docs/tasks/AUDIT.md` is the list of what is still open.
What counts as "passed" and when to merge: `docs/tasks/RELEASE-CANDIDATE.md` section 1 (a row passes only when walked on the release-candidate pair;
merge only when every check has finished, polled by run id, and `main`'s own run is green before the next step).

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
* **Never print, log, screenshot or paste a password.** Type passwords on test devices with `python -I tools/journeys/ui.py typefile <login file>` (it types only the `password:` line and prints nothing).
* **Never burst requests at YouTube** (at most 10 look-ups per test run, spaced) and never from a Host's home address unless the task says so.
* **Never make a client call an outside service** (YouTube, Deezer, lyrics, covers, anything): clients talk only to their own Encore server, the server talks to the
  outside, so a web or desktop client can exist later (`docs/11` ADR-R38).
* Ask the strongest model you have before committing to an architecture or any hard-to-undo choice, and again before calling a multi-step task done (`docs/30` §3).
* Do not start other tasks; file new problems as issues.
* **Never take, or offer the owner as an equal option, the easy choice that costs upgradeability, improvement or compatibility later.** Engineer the proper answer first: root cause with proof, the fix at the source; a stop-gap only with a removal trigger, a task and a reminder (the owner's standing rule, `docs/30` at the top; he repeats it every session).
* Do not touch the owner's homelab or anything outside this repository's own test machines (`docs/06` section 8).

## Where things are

| | |
|-|-|
| App | `app/` (Flutter project root: run `flutter` commands there) |
| Shared Dart package | `packages/encore_session` |
| Server | `server/encore_server` (the one server, since task P2-01); `server/legacy/*` are the older services, tested only when their own folder changes (D-44) |
| Checks | `tools/check.ps1` (`-Quick`, `-Server`, `-Live`) |
| Emulator driving | `tools/journeys/ui.py` (never tap blind: `dump` first) |
| Traps on this PC and how to avoid them | `docs/guides/dev-gotchas.md` |
