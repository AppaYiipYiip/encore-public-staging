# Encore: the reset plan (start here)

Written 2026-10-21 by the planning agent after reviewing the repository, the 60 old documents, the live server, the dev VM and
the app on an emulator, with measurements on the real line. **This folder replaces the old documents as the source of truth.** The old
documents are history; read one only when a task links it.

## What happened, in six lines

1. In five days (2026-10-14 → 18) agents made 249 commits, 60 docs, 109 decisions, an Android app (~59k lines) and seven server programs.
2. The core promise did not work: **a song you don't own took 38 s to start**. Owner's limit: 10 s worst case, near-instant normally.
3. The causes were measured: the server spent 33–35 s *searching* (up to 8 yt-dlp programs and 5 full YouTube pages per song), and
   the owner's homelab capped the server's download at 3 Mbit/s (now raised to 15). A lean search + one look-up in a running process
   reaches audio in **1.6–4 s**, even for a 2-hour recording; a 189-song playlist's list reads in **2–3 s**.
4. Side features (Jam, Year in Music, an admin site running a Firefox container to sign into Google, a Soulseek "quality tier", a
   recommendation engine) were built before the core worked; a walk through the app found 20+ problems the 1,430 tests missed.
5. The repository mixes in the owner's homelab, committed passwords, 50 APK files and another project's name, icon, licence and history.
6. Nobody wrote down what the product *is*, so every session re-decided it. `03` now does.

## The roles from now on

| Who | Does |
|-----|------|
| **Owner** | Answers the few product questions in `10` Part A; uses beta builds on real phones. |
| **Planning agent** (product owner / architect) | Thinks, researches, measures, writes and updates this plan and the task files. Does not write product code. |
| **Implementing agents** | Do the tasks in `tasks/`, one per branch, via pull requests, following `06`. |
| **Reviewing / QA agents** | Re-run each PR's acceptance criteria on devices and walk screens as a person (`07`); never review their own work. |

## Reading order

| # | File | What it is |
|---|------|-----------|
| 01 | [What is wrong, and why](01-what-is-wrong.md) | Every finding with evidence, root cause and the task that fixes it |
| 02 | [Questioning the premises](02-questioning-the-premises.md) | YouTube, server-side fetching, per-person folders, six services, Google sign-in, Soulseek, the inherited fork… each: why, does it hold, verdict |
| 03 | [The product](03-product.md) | Who it is for, positioning vs Spotify/Plexamp/free YouTube clients, promises with numbers, v1 scope, principles |
| 03a | [User stories](03a-user-stories.md) | v1 stories with acceptance criteria a tester can check |
| 04 | [Target architecture](04-architecture.md) | What runs where and why; the song-reference model; the fast play path; YouTube safety; many users at once; install design |
| 05 | [Repository, folders, GitHub](05-repo-and-file-structure.md) | Every folder with a verdict, the target layout, the new repo, GitHub, commit-and-push rules |
| 06 | [SDLC and agent workflow](06-sdlc-and-agent-workflow.md) | Life of a change, review, tracking, CI, doc rules, live-environment safety |
| 07 | [Testing and the device matrix](07-testing-and-device-matrix.md) | How to test like people use phones: profiles, conditions, journeys, test data, charters, checklist |
| 08 | [Roadmap](08-roadmap.md) | Phases P0–P6 with exit criteria (P4 = full feature set, P5 = public release) |
| 09 | [Research and measurements](09-research-and-measurements.md) | Every number and external fact, with setup and sources |
| 10 | [Decisions for the owner, and experiments](10-decisions-needed.md) | **Owner: please read Part A** |
| 11 | [Decision log (ADR-R1…R14)](11-decision-log.md) | The reset decisions with options compared |
| 12 | [The app's signing key](12-app-signing-key.md) | What it is, why losing it is bad, the agreed plan (plain words) |
| 13 | [Devices, volume, Jam and friends across servers](13-devices-jam-and-friends-across-servers.md) | Control the tablet from the phone (incl. volume), the volume bug, one account per person with servers that talk to each other, friends and Jams across servers |
| 14 | [Usability gaps and hidden risks](14-usability-and-hidden-risks.md) | What a Spotify user expects or a real phone will do that was not covered yet, with owners and new journeys |
| 15 | [Setup and first run, on paper](15-setup-and-first-run-on-paper.md) | Every page of the install, the setup wizard (8 steps), the app's first run and the admin site, before code |
| 16 | [Look and feel](16-look-and-feel.md) | Making Encore feel alive: your music as the art, colour, motion, illustrations, words |
| 17 | [API and sync contract](17-api-and-sync-contract.md) | Conventions, error codes, endpoints, live channel, offline merge rules, versions, timeouts |
| 18 | [Data model and migration](18-data-model-and-migration.md) | The server's and the phone's databases, and moving today's installs over without losing anything |
| 19 | [Catalogue, matching and search](19-catalogue-matching-and-search.md) | Song identity, normalisation (incl. Arabic), matching rules, search ranking, "Wrong song?", duplicates |
| 20 | [Recommendations design](20-recommendations-design.md) | The per-person profile, candidates, rows, cost, privacy, evaluation |
| 21 | [Security, privacy and roles](21-security-privacy-and-roles.md) | Roles, who sees what, public vs home routes, credentials, kids, leaving, threat model |
| 22 | [Operations and releases](22-operations-and-releases.md) | Updates with rollback, keeping yt-dlp fresh, backups, moving computers, capacity, scanning |
| 23 | [Downloads, formats, lyrics, notifications](23-downloads-formats-lyrics-notifications.md) | Formats per situation, the download manifest, server-side lyrics, notifications without push |
| 24 | [Observability and test environments](24-developer-observability-and-test-environments.md) | Request ids end to end, debug bundles, environments as code, recorded fixtures, kill switches |
| 25 | [Licences and third-party terms](25-licences-and-third-party-terms.md) | Every component's licence and every outside service's terms, with obligations |
| 26 | [Lifecycles and processes](26-lifecycles-and-processes.md) | Deep read of the code (sync storm, restore and stuck-player root causes), Android developer verification, the life of a song / playlist / phone / person / server, the server's day, the phone's battery budget |
| 27 | [Story map](27-story-map.md) | Every step of the Listener, the Host and the Tinkerer, marked designed / partial / missing, and the tasks the holes became |
| 28 | [Code-level re-engineering](28-code-level-re-engineering.md) | Module by module: what the code does today, what is structurally wrong, the target shape (player state machine, change feed, feature folders, one server package) |
| 29 | [Spotify gap review](29-spotify-gap-review.md) | Where Spotify does better, from the owner's walks |
| 30 | [Engineering guide](30-engineering-guide.md) | **Read before coding.** What to do and not to do, taken from what went wrong here, and which rules a machine checks; the thin-client rule; when to ask a stronger model; the PR self-review |
| 31 | [Connecting to a server](31-connecting-to-a-server.md) | The network, one address, who answers (the key), the race, signed in or not: states, words, tests |
| 32 | [Accounts, joining, devices](32-accounts-joining-and-devices.md) | Every way an account comes to exist, every way a phone joins, invitation / person / device states, limits |
| 33 | [Playback: sources, states, failures](33-playback-sources-states-and-failures.md) | Every way a song plays, the server's stream answers, the player's states, the failure matrix (internet cut mid-song and the rest), what is saved |
| 34 | [Conflicts and offline edits](34-conflicts-and-offline-edits.md) | The life of a queued edit, every pair of operations from two devices, other disagreements, the gaps |
| — | [tasks/](tasks/) | The work, phase by phase, with context and acceptance criteria |
| — | [evidence/](evidence/) | Screenshots from the app walk, the measurement scripts, and the clean-machine proofs (`c01` the installer, `c02` backup and restore, `c03` an interrupted install, `c04` the server updating its own yt-dlp; the app walks `b01` live channel, `b02` journey 4 on two phones) |
| — | [guides/](guides/) | The install test guide (`install-test.md`: one command on a fresh computer, backups, looking after it) and a draft guide for a friend using somebody's server (`friend.md`) |

## Ground rules that do not change

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

## State (2026-10-31)

The list of what is still open, task by task, with the owner's findings and the proof for each, is **[tasks/AUDIT.md](tasks/AUDIT.md)**; it is
kept current and this table only says where the phases stand.

| Item | State |
|------|-------|
| Review, measurements, app walk | Done (`01`, `09`, `evidence/`) |
| Repository | On GitHub (private). `main` has the CI workflows (app, server, server image, hygiene, screen pictures; Actions minutes were measured and cut in D-44); about 75 pull requests are merged; **`main` is not protected yet** |
| Owner decisions | **Decided:** D-2, D-3, D-4, D-5/D-9, D-7, D-10, D-11, D-17 (`10`). **Defaults in use, no objection:** D-1 GPL-3.0, D-6 YouTube on, D-12 quality tier off, D-13 to D-16. D-8 (agents push) works in practice |
| P0 Reset | Done except P0-09 (environments as code), P0-10 (licence inventory and check), branch protection and the project board |
| P1 Instant play | Core done (lean resolver, a player that cannot stick, offline, queue restore, covers); open items are listed in AUDIT (P1-03 legacy side, P1-04, P1-06, P1-07, P1-12, P1-13) |
| P2 Songs as references | Server core and the app's data layer done and walked; open items in AUDIT |
| P3 One server, one-command install | Installer slice, nightly backup and restore, and a resumable install are proved on clean machines (`evidence/c01` to `c03`); wizard, admin pages, update rollback, arm64 and the rest are open |
| P4 Full feature set, P5 Public release | Not started (the artist page and a first slice of profiles on a shared device exist) |
| **Current milestone** | The first outside user (P3-12, ADR-R34). Five checks, in order: the owner installed and uses the server; the away-from-home address works on mobile data; the data can come back (**done**); the friend's guide is final (draft); five days of the owner's own use |
| Next, in order | **Release candidate 1** (`tasks/RELEASE-CANDIDATE.md`): the fixes of the two review walks are committed and tested locally (pushed in order from 1 November), then three QA rounds with a testing agent, a clean-VM install test and a critic whose wishes the owner filters (section 5a); then the friend milestone below. The owner's one-page status is outside the repository |
| Before going public (P5-06) | The plan documents still name the owner's own machines and containers in several places (`06`, `09`, `11` and others); scrub them first |
| The old documents | History, kept only in the old repository's archive |
