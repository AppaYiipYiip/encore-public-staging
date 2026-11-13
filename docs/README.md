# Encore documentation (start here)

Encore is a music server you run at home and an app on your phone (and soon in a browser) that plays your music and, when a song is not on your server, fetches it for you. This folder is the plan, the design and the rules. **The roadmap board is the plan and the state**; everything else here is one of the kinds below.

## New here? Fifteen minutes, in this order

1. **What it is and where things are (5 min).** `README.md` (one screen), then `docs/guides/getting-started-for-developers.md` sections 1 and 2. Three programs: the Android app (`app/`, Flutter); the Encore server (`server/encore_server`, one Python program that sits beside a Navidrome music server and does everything the app asks, including YouTube, Deezer and lyrics, because the app only ever talks to its own server, ADR-R38); and the shared rules of listening together (`packages/encore_session`). `server/legacy/` holds the older separate services; do not build on them (B-16, P2-07).
2. **What is true now (3 min).** `python tools/roadmap.py brief --role agent`: who is working on what, what the owner reported, what is next. That output is the state; no document is.
3. **What is wrong or open (3 min).** The register `docs/tasks/AUDIT-BUILT-2026-11-05.md` lists findings `B-1` and up, each with its evidence, the proper fix and the item it lands in. For the item you take, `python tools/roadmap.py notes ITEM`: the pinned **detail** notes come first and name files, lines, traps and the tests that must change.
4. **How to change something (4 min).** `AGENTS.md`, your task in `docs/tasks/`, the truth documents it cites, `docs/30` (what to do and not to do) and `docs/06` (how a change goes).

**What the ids mean.** The same letters mean different things in different files; read an id with its file.

| Id | Means | Where it is defined |
|----|-------|---------------------|
| `P0-nn` to `P6-nn`, `N-nn` | a task on the board, an idea on the board | `docs/tasks/P*.md`, `docs/tasks/PROPOSED.md`, `docs/roadmap/` |
| `D-nn`, `X-n` | a decision for the owner, an experiment | `10` |
| `ADR-Rnn` | an architecture decision, with the options compared | `11` |
| `B-nn` **(with a hyphen)** | a finding about what is built, with evidence and the proper fix | `docs/tasks/AUDIT-BUILT-2026-11-05.md` (the open problems) |
| `B1` to `B34` (no hyphen) | the backend review of 30 to 31 Oct | `docs/history/README.md#qa-backend-2026-10-31` |
| `B0` to `B9` (no hyphen) | the check rows of the release candidate | `docs/tasks/RELEASE-CANDIDATE.md` |
| `B1` to `B8` (no hyphen) | the diagnosis of the old project | `01` |
| `F`, `Q`, `R1-`, `R2-F`, `M` | findings of the review rounds of 22 to 31 Oct (history) | `docs/history/README.md` |
| `A-nn` | a finding of the audit of 3 Nov 2026, cited in pull request titles | the workspace's `archive/` folder, outside the repository, read-only |
| `CN`, `AC`, `DV`, `IV`, `JN`, `PB`, `PB-F`, `CF`, `G`, `O` | one row of a state table: connecting, accounts, devices, invitations, joining, playback and its failures, conflicts, gaps, open questions | `31` to `34` (when you touch a state, update its row) |
| `US-nn` | a user story with its acceptance | `03a` |
| `S-nn`, `W-nn` | a phone screen; a Host's page in the browser (installer, admin), with the states each must show | `docs/design/00-screen-inventory.md` |
| `Hnn` (no hyphen) | a hidden risk | `13`, `14` |
| `c05`, `d01`, ... | a proof (evidence section) | `docs/evidence/README.md` |

**Three things that mislead a newcomer.** (1) A document of kind `history` or `evidence` is never an instruction; where it disagrees with a truth document, the truth wins. (2) *Built* is not *walked*: the board says "built, not walked" until the item is walked as a person on the release-candidate pair. (3) A document can promise what the code does not do (register rows B-63 and B-64 are two): the code is the fact; fix the document in the same pull request. The old test machines (VM 106, VM 107, CT 104) were destroyed on 3 Nov 2026; the test server is VM 108.

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
* **IDs never disappear** (D-62). `D-xx`, `ADR-Rxx`, `P*-nn`, `CN-1`, `PB-F7` are cited by code, tests and tools. The documents are being merged into about ten topic files; **a document's old number stays as the id of its section** (`## 17 · API and sync contract`), so `docs/17 section 5` in a source comment still finds `17.5`, and the **index of old numbers** below says which file holds each. `python docs/evidence/scripts/doc_ids.py diff docs/evidence/scripts/doc_ids.baseline.txt` proves that no ID was lost.
* **No new file for a message, a proof or a record.** Agents and developers talk to each other through **board notes** (`roadmap.py note`), never through a markdown file. A new proof is a new section at the end of `docs/evidence/README.md`; a new history record is a new section at the end of `docs/history/README.md`; a progress note is a board note. A new truth document or task file is added to the map below in the same pull request: `tools/check_docs.py` refuses the merge otherwise (the `map` and `links` rules are strict in CI).
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

## How a task file is written

A task has an **Order line** (`* **Order.** Needs: P2-08 [d], ...`: its place in the one list; `python -I tools/check_order.py` must pass and `--write` refreshes the table in `08`), then **Why** (the finding or story it serves), **Context** (files, measured numbers, gotchas), **Do** (the steps, in order), **Don't** (the traps), **Acceptance** (what a person sees, with numbers and the setup of `07` section 2), **Tests** (the levels of `07` section 6, the journeys of section 7), **Evidence in the PR**, **Depends on** and **Size** (S up to a day, M two to three, L four to five; split anything bigger). It holds the definition and nothing about how far it is: that is the board. Before any task: work in this repository; the test server is VM 108 `encore-install-test`, the owner's homelab is hands off; test accounts' login files are in `..\local\logins\` and a password is typed only with `python -I tools/journeys/ui.py typefile PATH` and never printed or photographed.

## Who does what

| Who | Does |
|-----|------|
| **Owner** | Decides what only he can (the pink items and the decisions in `10`); uses the app on his own phone. |
| **Planning agent** | Researches, measures, keeps the truth documents and the task definitions; does not write product code. |
| **Implementing agents** | Do the tasks, one per branch, by pull request, following `06`. |
| **Reviewing agents** | Re-run each pull request's acceptance on devices and walk the screens as a person (`07`); never review their own work. |

## Index of the old document numbers (D-62)

Source comments, tests and tools cite documents by number (`docs/17`, `31 CN-1`). Until a number appears in the table below it is still its own file with that number in its name. Documents that are merged get a section with their old number as id.

| Old number or path | Now |
|--------------------|-----|
| `history/reviews-2026-10-31.md`, `history/design-reviews.md` and their section ids (`#audit`, `#cloud-resume`, `#qa-backend-2026-10-31`, `#qa-round1-2026-10-31`, `#qa-ui-2026-10-31`, `#docs-audit-2026-11-01`, `#ux-review`, `#rc-rehearsal-vm107`, `#rc-log`, `#design-01-brief` to `#design-04-review-2026-10-30`) | `history/README.md`, the same ids |

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
| `THIRD_PARTY_NOTICES.md` | policy | The licences of what Encore ships or runs beside, in short | keep |
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
| `docs/design/README.md` | entry | How the drawings are organised | keep |
| `docs/evidence/README.md` | evidence | All the proofs behind the board's marks, one section per ID (`b01` to `c08` and the dated walks); a new proof is a new section here | append only; cited by the board |
| `docs/guides/dev-gotchas.md` | guide | Developer gotchas: traps met on this project's Windows PC and the pattern that works | keep |
| `docs/guides/friend.md` | guide | Using Encore on a friend's server (a one-page guide for the first outside user) | keep |
| `docs/guides/getting-started-for-developers.md` | guide | Getting started as a developer (read this first) | keep |
| `docs/guides/install-test.md` | guide | Install Encore on a fresh computer (the install test) | keep |
| `docs/history/README.md` | history | What happened, in short: the review records of 22 Oct to 5 Nov 2026 and the design records, with the finding IDs (F1 to F66, B1 to B34, Q, R1, R2-F, M1 to M8) explained in one line each; the long forms are in git at a pinned commit (D-62) | read-only; not instructions |
| `docs/roadmap/README.md` | entry | How the roadmap board works: one place per fact, who writes what | keep |
| `docs/tasks/AUDIT-BUILT-2026-11-05.md` | record | The audit of what is already built: findings with evidence, and the feasibility read | keep |
| `docs/tasks/P0-reset.md` | plan | The task definitions: P0 — Reset (no product changes) | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P1-instant-play-and-worst-bugs.md` | plan | The task definitions: P1 — Instant play, and stop the worst bugs | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P2-songs-as-references.md` | plan | The task definitions: P2 — Songs as references (the new library) | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P3-one-server-and-install.md` | plan | The task definitions: P3 — One server, one-command install | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P4-full-feature-set.md` | plan | The task definitions: P4 — Full feature set (in the first version, owner 2026-10-21) | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P5-public-release.md` | plan | The task definitions: P5 — Public release | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P6-later.md` | plan | The task definitions: P6 — Later (after the first public version; each needs a decision first) | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/P6-platforms.md` | plan | The task definitions: P6 — The last items: large screens (tablet and browser), TV, iPhone, and what stays parked | keep the definitions; move "Status" and "Done so far" narrative to the board's notes, one file at a time |
| `docs/tasks/PROPOSED.md` | plan | Ideas that are not scope until the owner says yes | keep |
| `docs/tasks/RELEASE-CANDIDATE.md` | plan | What must be true before the owner is told "ready": the walk checklist and the build log | keep the checklist; move the build log to the board |
| `server/legacy/encore-fetch/README.md` | legacy | encore-fetch | delete with `server/legacy` (audit B-16) |
| `server/legacy/encore-people/README.md` | legacy | encore-people | delete with `server/legacy` (audit B-16) |
| `server/legacy/reference/README.md` | legacy | Encore reference server | delete with `server/legacy` (audit B-16) |
| `server/legacy/reference/tests/vm/README.md` | legacy | Scripts for the dev VM (`encore-dev`, 192.168.50.133) | delete with `server/legacy` (audit B-16) |
| `tools/journeys/README.md` | guide | tools/journeys - driving the emulator like a person (docs/07 sections 3 and 12) | keep |
<!-- map:end -->
