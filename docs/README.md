# Encore documentation (start here)

Encore is a music server you run at home and an app on your phone (and soon in a browser) that plays your music and, when a song is not on your server, fetches it for you. This folder is the plan, the design and the rules. **The roadmap board is the plan and the state**; everything else here is one of the kinds below.

## How the documents work

There are five kinds of document, and each has one rule. A new document, or a new paragraph, goes into exactly one of them.

| Kind | Rule | Examples |
|------|------|----------|
| **Truth** | Says how things are and how they must be, in the present tense. **No dates, no "the owner said on...", no history, no status.** If a fact has a reason that matters, the reason is a decision ID. | `03`, `04`, `15`, `17`, `18`, `21`, `22`, `31` to `34`, the guides |
| **Decision** | A log: what was decided, why, the options, the date. Each decision is written **once**, here, and cited by its ID (`D-61`, `ADR-R7`) from everywhere else. | `10`, `11` |
| **Plan** | **Only the board** (`docs/roadmap/`: `order.json`, `items.json`, `status.json`, `notes/`) says what is planned and how far it is. The task files hold the definition of each task (what, why, acceptance, its needs) and nothing about how far it is. | `docs/roadmap/`, `docs/tasks/P*.md` |
| **State** | There is no state document. **`python tools/roadmap.py brief --role agent`** is the state: who is working on what, what the owner reported, what is next. Do not write a "where we are" page. | the board |
| **History** | Dated records of what happened. Append-only, **never instructions**; where one disagrees with a truth document the truth wins. | `docs/history/`, `docs/evidence/` |

Rules that follow from this:
* **Do not append a dated story to a truth document.** A change of fact changes the sentence. A decision goes in the log. A finding or a progress note goes on the board (`roadmap.py note`). What happened on a day goes in git, or in `docs/history/` if it will be needed.
* **IDs never change.** Files keep their names and numbers; `D-xx`, `ADR-Rxx`, `P*-nn`, `docs/31 CN-1` are cited by code, tests and tools.
* **Rewrite on touch.** A file marked "clean on touch" below is cleaned by whoever next edits it, in the same pull request.
* `python tools/check_docs.py` measures all of this (the map is complete, size, dated narrative in truth files, broken links). It reports today and will fail the build once the baseline is clean.

## Where to start

* **An AI agent or a developer:** `AGENTS.md`, then `python tools/roadmap.py brief --role agent` (the state), then your task in `docs/tasks/`, then the truth documents it cites. `docs/guides/getting-started-for-developers.md` is the first hour.
* **The owner:** the board (`roadmap.bat`); the pink items are the only things asked of him.
* **Somebody who wants to know why something is the way it is:** the decision log (`10`, `11`), then `docs/history/`.

## Ground rules that do not change

* **No easy choices that cost the future** (the owner's standing rule, repeated every session). Do not consider, choose or suggest the easy option that fixes the problem now but costs **upgradeability, improvement or compatibility** later. Spend the time to engineer the proper answer first: the root cause with proof, the fix at the source, a defensive layer only as a *second* layer that stays correct afterwards. When a stop-gap is truly unavoidable, say so, say what it costs later, and give it a removal trigger, a task for the proper fix and a visible reminder. Never offer "leave it as it is" as an equal option next to the proper one. Full text and the review checks: `30`.
* **Encore is a public product** (website with the guide, server download and APK). Nothing about the owner's homelab (addresses,
  container numbers, scripts, his request portal, his dashboard at `:8687`) belongs in Encore's code, docs or defaults.
* **No trace of the old project** (owner, 2026-10-21), done through a fresh repository (P0-04), after checking nothing copied remains.
* **Clients are thin** (owner, 2026-10-23, ADR-R38): the app, and any web, desktop or TV client later, talk only to their own Encore server; the server talks to YouTube, Deezer,
  lyrics and every other outside service. Always choose the solution that still works when the client is a browser. Today's exceptions and the tasks that remove them are in `11` ADR-R38.
* **Free for the user**: no feature depends on a paid account (no Tidal, no Spotify Premium, no Plex Pass).
* **For everyone**: other countries, weak PCs, slow or shared lines, flagged or blocked addresses, non-Latin text. Nothing may only
  work on the owner's setup. Never put a Host's internet address or accounts at risk.
* **Speed limits are requirements**: a song you don't own plays in ~2 s typically, **≤ 10 s worst case**; an import is on screen in
  ≤ 5 s; nobody waits for background downloads.
* **Never print, commit or screenshot a password.** Login files live outside the repository.
* **Say what was measured and on what setup.** "Tests pass" is not "it works".

## Who does what

| Who | Does |
|-----|------|
| **Owner** | Decides what only he can (the pink items and the decisions in `10`); uses the app on his own phone. |
| **Planning agent** | Researches, measures, keeps the truth documents and the task definitions; does not write product code. |
| **Implementing agents** | Do the tasks, one per branch, by pull request, following `06`. |
| **Reviewing agents** | Re-run each pull request's acceptance on devices and walk the screens as a person (`07`); never review their own work. |

## The map: every tracked markdown file

Kinds: `entry`, `truth`, `decision`, `plan`, `history`, `evidence`, `guide`, `record`, `policy`, `legacy`, `meta`. `tools/check_docs.py` reads this table: **a new markdown file must be added to it.**

<!-- map:begin -->
| File | Kind | What it is | Action |
|------|------|------------|--------|
| `.github/pull_request_template.md` | meta | What a pull request says | keep |
| `AGENTS.md` | entry | The rules for everyone who changes the repository (read first) | keep |
| `CHANGELOG.md` | record | What changed for a person, newest first | keep |
| `CLAUDE.md` | entry | A pointer to AGENTS.md | keep |
| `PRIVACY.md` | policy | The privacy statement | keep |
| `README.md` | entry | What Encore is, in one screen | keep |
| `SECURITY.md` | policy | How to report a vulnerability | keep |
| `docs/01-what-is-wrong.md` | history | The diagnosis of the old project (history; cited by number) | read-only; not instructions |
| `docs/02-questioning-the-premises.md` | history | Each premise of the old project questioned (history; cited by number) | read-only; not instructions |
| `docs/03-product.md` | truth | Who it is for, positioning vs Spotify/Plexamp/free YouTube clients, promises with numbers, v1 scope, principles | keep |
| `docs/03a-user-stories.md` | truth | v1 stories with acceptance criteria a tester can check | keep |
| `docs/04-architecture.md` | truth | What runs where and why; the song-reference model; the fast play path; YouTube safety; many users at once; install design | keep |
| `docs/05-repo-and-file-structure.md` | truth | Every folder with a verdict, the target layout, the new repo, GitHub, commit-and-push rules | clean on touch (dated narrative) |
| `docs/06-sdlc-and-agent-workflow.md` | truth | Life of a change, review, tracking, CI, doc rules, live-environment safety | keep |
| `docs/07-testing-and-device-matrix.md` | truth | How to test like people use phones: profiles, conditions, journeys, test data, charters, checklist | keep |
| `docs/08-roadmap.md` | plan | The plan explained, and the generated list (`tools/check_order.py --write`); the plan itself is `docs/roadmap/order.json` | generated part stays; the prose is cleaned on touch |
| `docs/09-research-and-measurements.md` | truth | Every number and external fact, with setup and sources | keep |
| `docs/10-decisions-needed.md` | decision | The owner's decisions (D-xx) and the open experiments; a decision is recorded once, here | keep; dated by nature (it is a log) |
| `docs/11-decision-log.md` | decision | The architecture decisions (ADR-R1 and later) with the options compared | keep; dated by nature (it is a log) |
| `docs/12-app-signing-key.md` | truth | What it is, why losing it is bad, the agreed plan (plain words) | clean on touch (dated narrative) |
| `docs/13-devices-jam-and-friends-across-servers.md` | truth | Control the tablet from the phone (incl. volume), the volume bug, one account per person with servers that talk to each other, friends and Jams across servers | keep |
| `docs/14-usability-and-hidden-risks.md` | truth | What a Spotify user expects or a real phone will do that was not covered yet, with owners and new journeys | keep |
| `docs/15-setup-and-first-run-on-paper.md` | truth | Every page of the install, the setup wizard (8 steps), the app's first run and the admin site, before code | keep |
| `docs/16-look-and-feel.md` | truth | Making Encore feel alive: your music as the art, colour, motion, illustrations, words | keep |
| `docs/17-api-and-sync-contract.md` | truth | Conventions, error codes, endpoints, live channel, offline merge rules, versions, timeouts | keep |
| `docs/18-data-model-and-migration.md` | truth | The server's and the phone's databases, and moving today's installs over without losing anything | keep |
| `docs/19-catalogue-matching-and-search.md` | truth | Song identity, normalisation (incl. Arabic), matching rules, search ranking, "Wrong song?", duplicates | keep |
| `docs/20-recommendations-design.md` | truth | The per-person profile, candidates, rows, cost, privacy, evaluation | keep |
| `docs/21-security-privacy-and-roles.md` | truth | Roles, who sees what, public vs home routes, credentials, kids, leaving, threat model | keep |
| `docs/22-operations-and-releases.md` | truth | Updates with rollback, keeping yt-dlp fresh, backups, moving computers, capacity, scanning | keep |
| `docs/23-downloads-formats-lyrics-notifications.md` | truth | Formats per situation, the download manifest, server-side lyrics, notifications without push | keep |
| `docs/24-developer-observability-and-test-environments.md` | truth | Request ids end to end, debug bundles, environments as code, recorded fixtures, kill switches | keep |
| `docs/25-licences-and-third-party-terms.md` | truth | Every component's licence and every outside service's terms, with obligations | keep |
| `docs/26-lifecycles-and-processes.md` | truth | Deep read of the code (sync storm, restore and stuck-player root causes), Android developer verification, the life of a song / playlist / phone / person / server, the server's day, the phone's battery budget | keep |
| `docs/27-story-map.md` | truth | Every step of the Listener, the Host and the Tinkerer, marked designed / partial / missing, and the tasks the holes became | keep |
| `docs/28-code-level-re-engineering.md` | truth | Module by module: what the code does today, what is structurally wrong, the target shape (player state machine, change feed, feature folders, one server package) | keep |
| `docs/29-spotify-gap-review.md` | truth | Where Spotify does better, from the owner's walks | clean on touch (dated narrative) |
| `docs/30-engineering-guide.md` | truth | **Read before coding.** What to do and not to do, taken from what went wrong here, and which rules a machine checks; the thin-client rule; when to ask a stronger model; the PR self-review | keep |
| `docs/31-connecting-to-a-server.md` | truth | The network, one address, who answers (the key), the race, signed in or not: states, words, tests | clean on touch (dated narrative) |
| `docs/32-accounts-joining-and-devices.md` | truth | Every way an account comes to exist, every way a phone joins, invitation / person / device states, limits | keep |
| `docs/33-playback-sources-states-and-failures.md` | truth | Every way a song plays, the server's stream answers, the player's states, the failure matrix (internet cut mid-song and the rest), what is saved | clean on touch (long) |
| `docs/34-conflicts-and-offline-edits.md` | truth | The life of a queued edit, every pair of operations from two devices, other disagreements, the gaps | keep |
| `docs/README.md` | entry | This map and the rules for the documents | keep |
| `docs/design/00-screen-inventory.md` | truth | Every screen and the states each must show | keep |
| `docs/design/01-brief-three-directions.md` | history | The brief for the three drawn directions (history) | read-only; not instructions |
| `docs/design/02-direction-choice.md` | history | Which direction was chosen and why (history) | read-only; not instructions |
| `docs/design/README.md` | entry | How the drawings are organised | keep |
| `docs/evidence/2026-10-22-walk-e1-e2-e6.md` | evidence | Device walk 2026-10-22: E1, E2, E6 on the emulator (build 100, from the new repo) | keep; cited by the board |
| `docs/evidence/2026-10-30-ux-batch1.md` | evidence | UX review, batch 1: the build next to the frame (2026-10-30) | keep; cited by the board |
| `docs/evidence/2026-10-30-ux-batch2-and-drawer.md` | evidence | UX review batch 2, and the drawer walked on an emulator (2026-10-30, night) | keep; cited by the board |
| `docs/evidence/b01-live-channel-two-phones.md` | evidence | B-01 — The live channel: one person, two phones (2026-10-22, build 113) | keep; cited by the board |
| `docs/evidence/b02-journey4-two-phones.md` | evidence | B-02 — Journey 4: one person, two phones, an import, a like and an edit (2026-10-23, build 120) | keep; cited by the board |
| `docs/evidence/b03-impostor-and-cold-start.md` | evidence | B-03 — Another server at the saved address, and the cost of the check (2026-10-24, build 120 before / slice A after) | keep; cited by the board |
| `docs/evidence/b04-server-away-during-playback.md` | evidence | B-04 — The server goes away while a song is asked for or playing (2026-10-24, G-1, build 120 from `task/G-1-wait-for-the-server`) | keep; cited by the board |
| `docs/evidence/b05-sign-out-and-a-stale-password.md` | evidence | B-05 — Signing out ends the phone's device on the server; a phone with an old password locked the account (2026-10-24, D-5) | keep; cited by the board |
| `docs/evidence/b06-no-phone-notifications.md` | evidence | B-06 — No phone notification unless the person asks, and the media controls still show (2026-10-24, ADR-R44) | keep; cited by the board |
| `docs/evidence/b07-signed-addresses.md` | evidence | B-07 — In Encore mode a song and a picture come by the server's signed address, with no login of the music server in either (2026-10-25, P2-20 slice 2) | keep; cited by the board |
| `docs/evidence/b08-rewalk-of-main-2026-10-30.md` | evidence | B-08 — A re-walk of what the notes call done, on `main` (2026-10-30) | keep; cited by the board |
| `docs/evidence/b09-p220b-rewalk-and-first-download.md` | evidence | B-09 — PR #33 (P2-20 slice 2) walked on the branch brought up to date with `main` (2026-10-30) | keep; cited by the board |
| `docs/evidence/b10-f21-download-of-a-release.md` | evidence | B-10 — F21: Download on a catalogue release, on the build of PR #43 (2026-10-30) | keep; cited by the board |
| `docs/evidence/c01-installer-clean-vm.md` | evidence | C-01 — The installer on a clean machine (2026-10-22) | keep; cited by the board |
| `docs/evidence/c02-backup-restore.md` | evidence | C-02 — Backup and restore on real machines (2026-10-23) | keep; cited by the board |
| `docs/evidence/c03-interrupted-install.md` | evidence | C-03 — An install that is cut short, and the music server's sign-in limit (2026-10-23) | keep; cited by the board |
| `docs/evidence/c04-ytdlp-self-update.md` | evidence | c04 — The server updates its own yt-dlp (P3-08b, ADR-R39), run for real | keep; cited by the board |
| `docs/evidence/c05-funnel-on-a-real-server.md` | evidence | c05: `encore funnel on` on a real server, a real Tailscale sign-in, 2026-11-03 | keep; cited by the board |
| `docs/evidence/c06-install-by-the-guide-bare-vm.md` | evidence | c06: the install by the guide, on a bare machine (3 November 2026) | keep; cited by the board |
| `docs/evidence/c07-download-notification-ask.md` | evidence | c07: the question about download progress, on an emulator (5 November 2026) | keep; cited by the board |
| `docs/evidence/c08-the-offline-look.md` | evidence | c08: the lasting offline look and the "Can't reach your server." strip, on an emulator (5 November 2026) | keep; cited by the board |
| `docs/guides/dev-gotchas.md` | guide | Developer gotchas: traps met on this project's Windows PC and the pattern that works | keep |
| `docs/guides/friend.md` | guide | Using Encore on a friend's server (a one-page guide for the first outside user) | keep |
| `docs/guides/getting-started-for-developers.md` | guide | Getting started as a developer (read this first) | keep |
| `docs/guides/install-test.md` | guide | Install Encore on a fresh computer (the install test) | keep |
| `docs/history/CLOUD-RESUME.md` | history | Resume from the repository alone (written 2026-11-01, the day the weekly usage limit ran out) | read-only; not instructions |
| `docs/history/DOCS-AUDIT-2026-11-01.md` | history | Docs coherence audit, 2026-10-31 night (two read-only agents, 80 markdown files) | read-only; not instructions |
| `docs/history/QA-BACKEND-2026-10-31.md` | history | The backend review, 2026-10-30/31: findings, triage and the order to fix them | read-only; not instructions |
| `docs/history/QA-ROUND1-2026-10-31.md` | history | QA round 1 and the owner's first field test (2026-10-31): findings and their triage | read-only; not instructions |
| `docs/history/QA-UI-2026-10-31.md` | history | The phone-app walk by a testing agent, 2026-10-30/31: findings and triage | read-only; not instructions |
| `docs/history/README.md` | history | What a history record is and the index of the moved ones | read-only; not instructions |
| `docs/history/design-03-owner-review-2026-10-24.md` | history | Design 03 — The owner's review of the three drawings (2026-10-24), one verdict per point | read-only; not instructions |
| `docs/history/design-04-review-2026-10-30.md` | history | Design 04: the review of every drawn screen against what is built (2026-10-30) | read-only; not instructions |
| `docs/roadmap/README.md` | entry | How the roadmap board works: one place per fact, who writes what | keep |
| `docs/tasks/AUDIT-BUILT-2026-11-05.md` | record | The audit of what is already built: findings with evidence, and the feasibility read | keep |
| `docs/tasks/AUDIT.md` | plan | What is not finished or only partly (living; its open rows move to the board, then it is archived) | move the open rows to the board, then archive |
| `docs/tasks/P0-reset.md` | plan | The task definitions: P0 — Reset (no product changes) | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P1-instant-play-and-worst-bugs.md` | plan | The task definitions: P1 — Instant play, and stop the worst bugs | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P2-songs-as-references.md` | plan | The task definitions: P2 — Songs as references (the new library) | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P3-one-server-and-install.md` | plan | The task definitions: P3 — One server, one-command install | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P4-full-feature-set.md` | plan | The task definitions: P4 — Full feature set (in the first version, owner 2026-10-21) | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P5-public-release.md` | plan | The task definitions: P5 — Public release | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P6-later.md` | plan | The task definitions: P6 — Later (after the first public version; each needs a decision first) | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P6-platforms.md` | plan | The task definitions: P6 — The last items: large screens (tablet and browser), TV, iPhone, and what stays parked | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/PROPOSED.md` | plan | Ideas that are not scope until the owner says yes | keep |
| `docs/tasks/README.md` | entry | How the task files are used | keep |
| `docs/tasks/RELEASE-CANDIDATE.md` | plan | What must be true before the owner is told "ready": the walk checklist and the build log | keep the checklist; move the build log to the board |
| `docs/tasks/UX-REVIEW.md` | record | The review of every control of the phone app | keep |
| `server/legacy/encore-fetch/README.md` | legacy | encore-fetch | delete with `server/legacy` (audit B-16) |
| `server/legacy/encore-people/README.md` | legacy | encore-people | delete with `server/legacy` (audit B-16) |
| `server/legacy/reference/README.md` | legacy | Encore reference server | delete with `server/legacy` (audit B-16) |
| `server/legacy/reference/tests/vm/README.md` | legacy | Scripts for the dev VM (`encore-dev`, 192.168.50.133) | delete with `server/legacy` (audit B-16) |
| `tools/journeys/README.md` | guide | tools/journeys - driving the emulator like a person (docs/07 sections 3 and 12) | keep |
<!-- map:end -->
