# 08 — Roadmap

Task details: [`tasks/`](tasks/). **Time is the position in the one list in the next section (no phases, D-57); a task prefix such as P2 is only a topic.** Tasks that do not need each other can run in parallel (one agent each). An item is done only when it is walked **with evidence** (`07` §11).

Owner (2026-10-21): **everything goes into the first version**, even if the release waits months. So the full feature set (P4)
comes before the public release (P5); the core (P1–P3) comes first so those features stand on the new design.

## The plan (read this first)

*Written 2026-11-03 from a read of all 80 tasks (72 of them had no dependency written down), reviewed by the advisor. It first came as phases (M0 to M11). On 2026-11-04 the owner asked for **no phases or groups at all, one list where everything can be mixed** (D-57), so the phases are gone: the plan is one ordered list, and what each phase used to demand now sits on the items it constrains (see "What the old phases demanded").*

**Now and Later (D-58, owner 2026-11-04).** Android and the browser version come first: the server fully set up, a complete recommendation system, every feature and gimmick working. The server on ARM, the tablet, the iPhone and the TV are **Later**: future work to keep in mind, not to bother with now, and not counted in the estimate. Rules that keep Later possible while building Now are in `AGENTS.md`.

**A task id (P2-12) names a topic, never a time. Time is the position in the list.** Where each fact lives (one place each, so nothing can disagree):

| File | Holds | Who changes it |
|------|-------|----------------|
| `docs/tasks/P*.md` | what a task is, its size, and its needs: `* **Order.** Needs: P2-08 [d], P2-09 [i]. Why: ...` | agents, in the PR of the work |
| `docs/roadmap/order.json` | **Now** (`order`: the one list, the sequence of what is not walked yet) and **Later** (`later`: future work to keep in mind and not bother with, D-58); item ids only | **the owner**, by dragging on the board (a move carries what the item needs) |
| `docs/roadmap/status.json` | `todo`, `built` (built, not walked) or `walked` (with its proof, a time and who) | agents only, with `python tools/roadmap.py mark`, in the PR of the work |
| `docs/roadmap/items.json` | plain-words titles, kinds, notes, `judge` flags, and the not-yet-accepted proposals (`tasks/PROPOSED.md`) | agents; the board adds an idea typed on it (`pending` until its row in `PROPOSED.md` exists) |
| `docs/roadmap/notes/<ITEM>/*.json` | the **conversation**: notes, details (how an item should turn out), the owner's checks and problem reports; one file per note, never edited | **anyone**: the board page (the owner), or `python tools/roadmap.py note` |
| `<clone>/.git/encore-working/` (never committed) | **Working now**: what each Claude session announced, and when it last said so; shared by every worktree on the computer | the Claude sessions: `python tools/roadmap.py start / update / done` |
| this file | the explanation; the list inside it is **generated** | the text by hand, the list by `tools/check_order.py --write` |

A need is **`[d]` declared** in the task's own text, **`[i]` inferred** (technical: it cannot be built without it) or **`[p]` policy** (a rule the project chose, such as "the tablet only after the public release"). `tools/check_order.py` (it runs in CI) fails when an item comes *before* something it hard-needs, a task has no Order line, an id is missing or repeated, an entry of `order.json` is not an id, a status says walked without a proof, or the generated list is stale. A policy need only **warns**: the owner may drag past it knowingly.

**The local board is the project's shared memory** (for the owner and every Claude session; developers read the same files). Double-click `roadmap.bat` in the workspace folder (or run `python tools/roadmap_board.py`): it opens in its own window with no address bar (a bookmark address, `http://roadmap.localhost:8765/`, also works). It is a page on your own computer, no cloud and no account, so it works the same whichever Claude account you are signed in to, and it is **the owner's**: it always writes as him. It shows **Working now** (what Claude announced; a claim quiet for 8 hours is flagged "may have stopped"), **Waiting for you** (questions to you, and Claude's ideas that need your yes), **Add an idea** (it goes straight into the list), a progress line, and the **one list**: drag an item (or use the arrows), see each item's size in Claude working days and a live "ready around working day X to Y", open any item to write **details** and notes, and press **its buttons** (below). It refuses a drop that breaks a hard need and warns about a policy need. At the start of a session a Claude session turns any uncommitted change under `docs/roadmap/` into a documentation PR before anything else; the command every session starts with is `python tools/roadmap.py brief`. Formats, rules and the trust model: `docs/roadmap/README.md`.

### What "done" means (and who checks it)

Every row has a mark: **empty = not done; half = built but not proven yet; a tick = done, with its proof on the row; a red "!" = the owner reported a problem**. Done items stay in the same list, greyed at the top (a switch hides them). The word is the owner's own definition of pass (`tasks/RELEASE-CANDIDATE.md` section 1): **walked as a person on the release-candidate pair (the published image plus the app built from the same commit) on a clean machine, to the end state.** Anything less is `built`, "built, not walked", however well it was tested. Process tasks are walked by their own check, which is what the proof names.

* **Claude marks** an item with `python tools/roadmap.py mark ITEM built|walked --evidence "..."` in the PR of the work. `walked` refuses a missing proof, takes the item out of `order.json` in the same step, and cites the owner's own check when there is one.
* **The owner's buttons never prove an engineering item** (he is not the tester): *I did this* only on an item that needs him (protect `main`, the keystore): his word is the proof; *I checked it* only where his own judgement is part of the acceptance (`judge`): recorded, cited when Claude proves the item; *It doesn't work* on anything built or done: it reopens the item at the front of the list (never before something it needs) and leaves Claude a note waiting; *Not done after all* takes a check back. They write **notes**, and the state shown is derived from `status.json` plus those notes, so `status.json` keeps one writer.

### Why the list is in this order (the questions of 2026-11-03)

* **Suggestions come right after Jam, not after the cross-server work.** They are what makes daily use compelling for every user from the first day, and the owner's own acceptance is "does Home know me?" after a week. Federation only matters once there are several servers.
* **Notification when an artist you follow releases something** has three parts: the server's daily check (P2-15, it replaces the phone calling Deezer), the follow and the shelf (P4-18) and the phone notification, which stays **opt-in** (ADR-R44; D-52 allows the one exception for download progress only).
* **"Not for me"** is part of P4-01 (`POST recs/feedback`, `17`): a person's dislike changes only that person's rows.
* **Design before building, on Android first.** The phone's drawings exist; the large-screen drawings are the first large-screen task (P6-01) and are drawn by the planning agent and approved by the owner before any code (D-43). All of that is Android and the browser, long before the iPhone.
* **Browser or tablet first?** They share their main cost, the large-screen layouts. If the browser player is built from the same Flutter code (recommended: one design system, no second app to maintain), the tablet layouts must exist first and the browser reuses them. If the owner prefers a separate web app, the browser could go earlier but it becomes a second code base for ever. This is **D-55**, to be decided.
* **The iPhone is last, and it is the only item whose feasibility is decided outside the project.** The app is distributed on GitHub only (D-56): there is no App Store, no TestFlight and no Apple developer account, so an iPhone version can only be installed by sideloading, which the checking task (P6-04) verifies before any code; a "no" is a result, not a delay. A browser that works on an iPhone may already cover part of the need.

### What the old phases demanded, and where it lives now

The first draft of this plan had twelve phases with a gate each. They are gone (D-57); every condition that mattered is now enforced on the item it constrains, so nothing was lost and nothing groups the list:

| The old gate (history) | Where it is now |
|------------------------|-----------------|
| The release-candidate pair is walked on a clean machine, signed with the release key, with the walk record `b11`, the advisor and the critic; the open round-2 findings are fixed or triaged | **P0-13** (a task of its own), which needs the release key (P5-01), the offline indicator (P1-15), the download state (P2-22) and every built item it walks |
| The first friend can connect: five checks, a forced bad update rolls back, the security review and the first ultrareview are done, a lost password can be recovered | **P3-12** needs P0-13, P3-14 (rollback), P3-15 (security review + first ultrareview), P3-16 (password recovery), P5-01 (the key) and P5-07 (the install guide); its five checks are its acceptance |
| The thin client and the device model: the app talks only to its own server (the outside-host ratchet baseline empty), the API contract checked in CI, the device token only, a first screen with no IP address, resume anywhere and one device at a time, new-release checks done by the server | acceptance of P2-12, P2-14 and P2-15 (each lowers the ratchet), P2-20 (device token only; the baseline is empty; it needs P2-15 as a policy need), P2-23 (the contract in CI), P2-19 (no IP address), P2-08 and P2-09 (resume anywhere, one device at a time) |
| Jam and Connect pass on two emulators; Discover (suggestions, smart shuffle, "Not for me", follow with a notification) walked, the owner rates his own Home after a week | acceptance of P4-02, P4-07, P4-01, P4-18; the owner's own checks are `judge` items (his tick is recorded and cited) |
| The host pages and wider installs: install in at most 15 minutes on a fresh x86 and a fresh ARM64 machine, one published port, the Health page explains every state, the full privacy matrix, the update path complete | acceptance of P3-05 (both machines), P3-07 (at most 15 minutes on TYPICAL), P3-01 (one published port), P3-06 (the Home page explains every state), P3-09 (the privacy matrix), P3-08 (updates with rollback, moving computers) |
| Two servers: friends by QR in 30 s, removing a friend stops all sharing, a forged request is refused, a capture of a cross-server Jam shows only the guest's own server; the federation code reviewed by an ultrareview before it merges | acceptance of P4-09 and P4-08 (and its "Before it merges" line: the owner runs `/code-review ultra`); P4-10 |
| Quality, polish and extras: the quality tier upgrades a kept song without moving a like, a playlist place or a resume position; "Wrong song?"; the Spotify-class extras each walked; Spotify beyond 100 songs | acceptance of P4-04, P4-14, P4-12, P2-06 |
| The whole app walked, no open S1 or S2, every promise N1 to N11 measured on SLOW and TYPICAL and on two real phones, five days without opening Spotify, scrub list, licence inventory, the third ultrareview, `v1.0.0` | P4-06 and P5-03 (their acceptance; the promises are in `03` §4), P0-10 (licences), P5-06's own "Before it" lines and acceptance |
| Large screens (drawings approved first; both orientations and split screen; the browser's capture shows only the home server), Android TV (D-pad only; sign-in by a code), iPhone | acceptance of P6-01, P4-11, P6-02, P6-03; P6-04 to P6-06 (D-56) |
| What each phase needed from the owner | a pinned **detail** on the item ("Owner's part: ...") and the kind "Needs you" on the items only he can do |

### What the sweep found missing

The sweep read every user story, README promise, ADR consequence, AUDIT row, the round-2 findings, the audit's open items, the release-candidate debts, the ratchet baselines and `P6-later.md`. New tasks, each with its evidence in its own text:

| New task | What | Evidence |
|----------|------|----------|
| P0-11 | CI upkeep and the toolchain (Node 24 actions, pinned runner, Gradle/AGP/Kotlin, issue #41) | `RELEASE-CANDIDATE.md` §5 debts, AUDIT P0, the audit's A-17 |
| P0-12 | The four open documentation-honesty items (A-1, A-6, A-15, A-16) | the audit of 3 Nov |
| P0-13 | Release candidate 1 walked (the old first gate, now a task of its own) | `RELEASE-CANDIDATE.md`, D-57 |
| P1-15 | The app says when it is offline | round 2, R2-F5 |
| P2-23 | One API contract checked in CI | ADR-R41 T5, AUDIT P2-01 |
| P3-14 | Update with automatic rollback | P3-12's own warning; `22` |
| P3-15 | Security review and first ultrareview before the first outside user | P3-09 said "before P5", but exposure starts at P3-12 |
| P3-16 | The Host can recover a lost password | `credentials-map.md`: "not built yet" |
| P4-18 | Follow artists and the release notification | the owner's question of 3 Nov; server `follows` built, phone check calls Deezer |
| P6-01 to P6-07 | Drawings, browser, TV, iPhone, casting | D-54, `P6-later.md` |

`tasks/PROPOSED.md` lists more ideas that are **not scope** until the owner accepts them.

### How long (the method, so it can be recomputed)

* **Size to effort (an assumption, only a way to compare tasks):** S = 1, M = 3, L = 7 Claude Code working days for **one** agent. The plan never defined them before.
* **Speed (measured):** this repository's first commit (2026-10-21) is "initial import of the app, server and docs", so three of the tasks that look done (P1-08 player never stuck, P1-09 offline, P1-11 resume after a kill) came in with the import and are **left out**. The 15 tasks finished by new work add up to 51 Claude-days over the 10 weekdays from 21 Oct to 3 Nov: **about 5.1 Claude-days per weekday for the whole team** (`RATE` in `tools/roadmap_plan.py`). Sensitivity: counted from 14 Oct, when the earlier project started, it would be about 3.9, which would push the total toward 20 to 40 weeks. An earlier draft of this page said the first guess ("agents times a factor") was too pessimistic; that was based on a speed that counted the moved-in tasks, and it was wrong. Recompute when a large item lands (`gh pr list --state merged`).
* **Slowdown (a stated judgement):** the first two weeks were the greenfield part, with several agents in parallel and the owner away for long stretches. What is left needs the owner (the signing key, the real server, the hardware), real devices (Jam on two phones, a TV, iPhones), outside gates and Claude's weekly usage limit, which has stopped the work twice already (1 Nov and 3 Nov). So elapsed time is the base speed times **1.5 to 3**.
* **A floor for one big task:** one L task cannot be split across agents, so an item is never shorter than its longest chain of needs in Claude-days (a lone L is at least 7 working days; Android TV was wrongly shown as 2 to 3). The estimate is the larger of the chain and the speed-based figure.
* **Built but not walked** costs a quarter of its size (the walk and the fixes it finds); a **reopened** item costs the same (a fix and a new walk); **walked** costs nothing.
* **Not in the numbers:** external waits and the owner's own steps (making the key, installing the real server), which are named on the items that need him.
* **Result:** an item's "ready around working day X to Y" is cumulative in the order of the list, so dragging an item changes everything after it. The total adds up the **whole list**, parked items included (before 2026-11-04 the parked ones were left out: that is why the total grew). **Never a date.**

### The plan (generated)

<!-- order:begin (generated by tools/check_order.py --write; do not edit by hand) -->

**The plan, in order** (one list, top = next): 88 items still to do, 10 of them built and waiting for a walk, 9 done. About 242.5 Claude-days of work left, so roughly **71 to 143 working days** (about 14 to 29 weeks) elapsed in all (external waits and the owner's own steps are not in it). A range from a stated method, never a date. `*` marks a policy need (a rule the project chose, which the owner may override).

| # | Item | What | Size | State | Needs | Ready around working day |
|---|------|------|------|-------|-------|--------------------------|
| 1 | P0-11 | Behind the scenes: keep the automatic checks and build tools up to date | S | todo | none | 1 to 2 |
| 2 | P0-12 | Behind the scenes: fix the places where the documents promise more than the app does | S | todo | none | 1 to 2 |
| 3 | P1-01 | Songs you do not own start playing in about 2 seconds | M | built | none | 1 to 2 |
| 4 | P1-02 | Playing starts first; size limits only apply when you keep a song | M | built | none | 1 to 2 |
| 5 | P1-05 | Imported playlists play the same video they came with | S | built | none | 1 to 2 |
| 6 | P1-06 | Behind the scenes: tools that measure how fast the app really feels | S | built | none | 1 to 2 |
| 7 | P1-08 | The player never gets stuck | M | built | none | 1 to 3 |
| 8 | P1-11 | Playback resumes after the phone closes the app, with the right lock-screen position | S | built | none | 1 to 3 |
| 9 | P1-04 | The next songs are prepared before you tap them | S | todo | none | 2 to 4 |
| 10 | P1-15 | The app tells you when you are offline | S | todo | none | 2 to 4 |
| 11 | P2-02 | Behind the scenes: the app's database rebuilt around songs as entries | L | built | none | 3 to 5 |
| 12 | P1-10 | Covers show everywhere, also when you are offline | M | todo | none | 3 to 7 |
| 13 | P2-03 | Playing something is not saving it; albums play even for songs you do not own | M | built | none | 4 to 7 |
| 14 | P2-22 | A download shows where it is: progress, a notification, and why if it stops | M | todo | none | 5 to 9 |
| 15 | P3-01 | Behind the scenes: the whole server is one program | L | built | none | 5 to 10 |
| 16 | P3-04 | Behind the scenes: risky leftovers removed (full control of the server computer, Firefox and Google sign-in) | S | built | none | 5 to 10 |
| 17 | P5-01 | Make your release key (so updates never force a reinstall) | S | todo | none | 5 to 10 |
| 18 | P0-13 | Before your first friend: Claude checks everything built so far, like a real user | M | todo | P1-01, P1-02, P1-05, P1-06, P1-08, P1-11, P2-02, P2-03, P3-01, P3-04, P1-15, P2-22, P5-01 | 6 to 12 |
| 19 | P3-14 | Server updates that undo themselves if something goes wrong | M | todo | none | 7 to 14 |
| 20 | P3-15 | Before your first friend: a security check of everything reachable from the internet | M | todo | none | 8 to 16 |
| 21 | P2-08 | Pick up where you left off on another device | M | todo | none | 9 to 17 |
| 22 | P3-16 | Reset a forgotten password with one command | S | todo | none | 9 to 18 |
| 23 | P5-07 | A guide that shows a friend how to install the app from GitHub | S | todo | P5-01 | 9 to 19 |
| 24 | P3-18 | Install your real server, with Claude guiding you step by step | S | todo | P3-05 | 9 to 19 |
| 25 | P3-19 | Start Claude's deep security review before your first friend (one command, it costs money) | S | todo | P3-15 | 9 to 19 |
| 26 | P3-12 | Your first friend uses your server from outside your home | M | todo | P3-05, P0-13, P3-18, P3-19, P3-14*, P3-15*, P3-16*, P5-01*, P5-07* | 10 to 20 |
| 27 | P1-07 | Search shows one clear best result at the top | M | todo | none | 11 to 22 |
| 28 | P1-13 | One volume and the same loudness for every song | M | todo | none | 12 to 24 |
| 29 | P2-05 | Importing has a stop button, shows progress and counts correctly | S | todo | none | 12 to 24 |
| 30 | P2-07 | Behind the scenes: remove leftover old code and a duplicate import screen | S | todo | none | 12 to 25 |
| 31 | P2-09 | One device plays at a time, like Spotify | M | todo | P2-08 | 13 to 27 |
| 32 | P4-02 | Jam: listen together | L | todo | P2-08, P2-09, P3-12* | 16 to 31 |
| 33 | P2-12 | Search and artist pages come from your own server | L | todo | none | 18 to 35 |
| 34 | P2-14 | Lyrics come from your own server | S | todo | none | 18 to 36 |
| 35 | P3-03 | Behind the scenes: each phone gets its own key to the server | M | todo | none | 19 to 37 |
| 36 | P2-15 | Your server checks for new releases; the news shows in the app | S | todo | P2-12 | 19 to 38 |
| 37 | P2-20 | Behind the scenes: the app keeps only a device key, not your music server password | L | todo | P2-12, P2-14, P3-03, P2-15* | 21 to 42 |
| 38 | P2-19 | The app finds your server without typing an address | L | todo | P2-20 | 23 to 46 |
| 39 | P3-10 | Add a device with a QR code; settings follow you; cancel a lost device | M | todo | P2-19 | 25 to 48 |
| 40 | P2-10 | Sign in by invitation, and bring your own music | M | todo | P2-19 | 25 to 50 |
| 41 | P2-13 | Downloads in the right format; stale files get replaced | M | todo | none | 26 to 51 |
| 42 | P2-18 | A changed or expired sign-in is handled calmly | M | todo | P3-03 | 27 to 53 |
| 43 | P2-21 | Playlist description and picture; select many songs at once | M | todo | none | 28 to 55 |
| 44 | P2-23 | Behind the scenes: one written rulebook that every app and the server follow | M | todo | none | 28 to 57 |
| 45 | P3-13 | You set a storage limit, and the server says plainly when it is full | M | todo | none | 29 to 59 |
| 46 | P2-06 | Spotify import works beyond 100 songs and brings your Liked Songs | M | todo | none | 30 to 60 |
| 47 | P4-07 | Control one device from another, with remote volume | L | todo | P2-08, P2-09 | 32 to 64 |
| 48 | P2-17 | Imported playlists can follow the original playlist | M | todo | none | 33 to 66 |
| 49 | P4-20 | Behind the scenes: choose how suggestions are made, a ready-made engine or our own | S | todo | P2-12 | 33 to 67 |
| 50 | P4-01 | A Home made for you: suggestions, smart shuffle, radio and "Not for me" | L | todo | P2-12, P4-20 | 35 to 71 |
| 51 | P4-05 | Your Year in Music, from what you really played | S | todo | none | 36 to 71 |
| 52 | P4-15 | Browse, history and playlist details | M | todo | P2-17 | 37 to 73 |
| 53 | P4-18 | Follow artists, and get told when one releases something | S | todo | P2-15 | 37 to 74 |
| 54 | P0-09 | Behind the scenes: one command starts a full test setup on any computer | M | todo | none | 38 to 76 |
| 55 | P2-16 | Behind the scenes: your library repairs itself after a restore | M | todo | none | 39 to 77 |
| 56 | P3-06 | A setup wizard and admin pages in the browser, on a PC | L | todo | P4-02* | 41 to 81 |
| 57 | P3-02 | Behind the scenes: the server packaged for Intel and AMD computers | S | todo | none | 41 to 82 |
| 58 | P3-07 | Proof that a fresh computer installs the server from the guide, also on a slow line | S | todo | P3-02 | 41 to 83 |
| 59 | P3-08 | Move the server to another computer, see statistics, and test restores every night | L | todo | P3-14 | 43 to 87 |
| 60 | P3-09 | Privacy rules tested; export your data; delete your account | M | todo | none | 44 to 89 |
| 61 | P3-11 | Use a music server you already run (for people who like tinkering) | M | todo | none | 45 to 90 |
| 62 | P4-03 | See what your friends listen to (only if they agree) | M | todo | none | 46 to 92 |
| 63 | P4-19 | Start Claude's deep security review of friends on other servers (one command, it costs money) | S | todo | none | 46 to 92 |
| 64 | P4-09 | Friends on other servers | L | todo | P0-09, P4-03, P4-19 | 48 to 96 |
| 65 | P4-08 | Behind the scenes: your phone only ever talks to your own server, even for friends' servers | M | todo | P4-09 | 49 to 98 |
| 66 | P4-10 | Jam across servers, sharing, and shared playlists | L | todo | P4-02, P4-09 | 51 to 102 |
| 67 | P4-17 | Compare music taste with a friend (only if they agree) | M | todo | P4-09 | 52 to 104 |
| 68 | P4-04 | Optional lossless (CD-quality) audio | L | todo | none | 54 to 108 |
| 69 | P4-12 | The extras Spotify has: Android Auto, a home-screen widget, crossfade and more | L | todo | none | 56 to 112 |
| 70 | P4-14 | "Wrong song?" fix, and editing song details | M | todo | P2-12 | 57 to 114 |
| 71 | P0-10 | Behind the scenes: check that every library we use may legally be used | S | todo | none | 57 to 114 |
| 72 | P1-12 | Big text, right-to-left languages and screen readers work | L | todo | none | 59 to 119 |
| 73 | P1-14 | Less syncing, so less battery and mobile data | S | todo | none | 60 to 119 |
| 74 | P6-01 | Drawings of the browser version, approved by you before any code | S | todo | none | 60 to 120 |
| 75 | P6-02 | The browser version: the same app in any desktop browser | L | todo | P6-01, P2-19, P2-23*, P2-20, P2-12, P2-14 | 62 to 124 |
| 76 | P4-06 | Before the public release: Claude walks the whole app again like a real user | M | todo | P4-02*, P4-07*, P4-09*, P4-10*, P4-01*, P4-04*, P6-02* | 63 to 126 |
| 77 | P5-02 | The app checks for updates by itself | S | todo | P5-01 | 63 to 126 |
| 78 | P5-03 | Claude tests on many phones, and you use the app without Spotify for 5 days | M+5 | todo | P4-06* | 65 to 131 |
| 79 | P5-04 | The app opens in under 0.7 seconds | M | todo | none | 66 to 133 |
| 80 | P5-09 | Start Claude's deep security review before going public (one command, it costs money) | S | todo | P5-03 | 66 to 133 |
| 81 | P5-06 | Make the code public on GitHub and publish the first release | S | todo | P5-03, P5-09, P0-10, P0-12, P3-09 | 66 to 133 |
| 82 | P5-08 | A "what's new" screen and help inside the app | S | todo | none | 67 to 133 |
| 83 | N-07 | A better logo and app icon | S | todo | none | 67 to 134 |
| 84 | N-09 | A first-run experience that feels designed | M | todo | none | 68 to 136 |
| 85 | N-08 | A fresh visual design for the phone app | L | todo | none | 70 to 140 |
| 86 | N-01 | Share a song, album or playlist as a link | M | todo | none | 71 to 141 |
| 87 | N-02 | Export a playlist as a file | S | todo | none | 71 to 142 |
| 88 | N-05 | Back up your music with one command | S | todo | none | 71 to 143 |

**Later** (15 items: future work to keep in mind and not bother with now, D-58; no estimate)

| Item | What | Size | Needs |
|------|------|------|-------|
| P3-17 | The server on ARM computers (Raspberry Pi and others) | M | P3-02 |
| P6-08 | Drawings of the tablet version | S | P6-01 |
| N-03 | Send what you play to ListenBrainz or Last.fm | M | none |
| N-04 | Get told when the server is down, full or YouTube is blocking it | M | none |
| N-06 | Podcasts and audiobooks | L | none |
| P6-07 | Casting to other speakers | M | none |
| P4-11 | Tablet version | M | P5-06*, P6-02, P6-08 |
| P6-03 | Android TV version | L | P6-02, P2-19, P2-23*, P2-20* |
| P4-16 | Profiles for several people on one device | L | P4-11, P3-03 |
| P6-04 | iPhone: can it be installed without Apple's store? (check first) | S | P2-23*, P2-20*, P2-12*, P2-14*, P5-06* |
| P6-05 | iPhone version of the app | L | P6-04 |
| P6-06 | iPhone: how people install it from GitHub | S | P6-05, P5-06* |
| P2-11 | Behind the scenes: move over installs from the old version (probably not needed: proposed to close) | L | none |
| P4-13 | Problem reports and battery-saver tips (shelved) | M | none |
| P5-05 | The website, the name and the legal texts | M | P3-07 |

**Done** (9 items with their proof; what is left inside them is in `tasks/AUDIT.md`)

| Item | What | Proof |
|------|------|-------|
| P0-01 | Behind the scenes: secrets and old leftovers cleaned out of the code | README State: P0 done; gitleaks runs in CI |
| P0-06 | Behind the scenes: automatic checks run on every change | CI runs on every change (workflows app, server, docs, goldens, server-image) |
| P0-07 | Protect the main branch on GitHub (nobody can overwrite your code by accident) | verified with gh api on 2026-11-04: ruleset 'protect main' (id 26569683) is active on the default branch, no bypass; blocks deletion and force push; a pull request is required (0 approvals); checks 'checks' and 'secrets' must pass |
| P0-08 | Behind the scenes: written rules so every Claude works the same way | AGENTS.md and docs/30 exist and the pre-commit hook enforces them |
| P1-03 | Behind the scenes: YouTube is asked gently, so your home address is never blocked | the 217-song YouTube import fetched through VM 108 in about 46 minutes with no refusal (build 125 pair, 3 Nov 2026; AUDIT round 2) |
| P1-09 | Offline: no skipping, greyed-out songs, and it recovers by itself | round 2 on build 125 against VM 108 (3 Nov 2026): a downloaded song plays offline, a row that is not downloaded says so (ROUND2-LOG) |
| P2-01 | Behind the scenes: the server's core, where a song is one entry whoever owns it | installed by the guide on a bare VM (evidence/c06); signed in, invited and imported against it in round 2 on build 125 (3 Nov 2026) |
| P2-04 | Import a playlist in seconds | the owner imported two playlists (4 and 217 songs) on build 125 against VM 108 (3 Nov 2026) |
| P3-05 | Install the server with one command | evidence/c06: the installer by the guide on a bare VM with the published image (3 Nov 2026); c01 and c03 earlier |

<!-- order:end -->

## The topics (what each task prefix is about, not when)

**History.** This is the original plan in seven phases (P0 to P6). Since 2026-11-04 (D-57) there are no phases or groups: the prefixes are only topics, every "exit" below is now enforced on the items (see "What the old phases demanded" above), and the effort figures are superseded by "How long".

| Topic (the old phase) | Goal in one line | Why it came in this order (history) |
|-------|------------------|-------------------|
| **P0 Reset** | A clean, safe, honest repository and process | Everything later lands in it; secrets and the old project's leftovers leave before anything is pushed again |
| **P1 Instant play, stop the worst bugs** | A song you don't own plays in ~2–3 s; the player never gets stuck; offline and covers work | The core promise is broken today (38 s); the fixes are reusable in the new design |
| **P2 Songs as references (the new library)** | Like/playlist/import/resume any song, owned or not; imports in seconds; one device at a time | Removes the root cause of the spaghetti (C3); delivers resume-anywhere and single-device playback |
| **P3 One server, one-command install** | One Encore server program, one port, device logins, published images, installer + browser wizard | Makes Encore installable by strangers and maintainable by agents |
| **P4 Full feature set** | Recommendations per person, Jam (also across servers), friends on other servers, your devices with remote volume, one account per person with servers talking to each other, quality tier, Year in Music, Spotify-class extras | Owner: everything in the first version |
| **P5 Public release** | Signed APK with updates, full device matrix, field test, going public (website and name when the owner wants) | The first public version |
| **P6 Later** | iOS, web/desktop client, devices remote control, localisation, "Encore OS" image | After the first public version |

## P0 — Reset (no product changes)

Tasks: P0-01 secrets out of git · P0-02 homelab out · P0-03 workspace clutter · P0-04 the new repository (clean tree, new layout,
nothing of the old project) · P0-05 rename, re-icon, licence · P0-06 CI for app and server · P0-07 GitHub set-up · P0-08 agent files ·
P0-09 environments as code · P0-10 licence inventory and checks.
**Old phase exit (history; the items enforce it now):** the new repo `encore` on GitHub with `main` protected, CI green on the moved code, no secret or binary in history
(`gitleaks` clean), no trace of the old project's name in the repository, the old repo renamed `old-repo` and archived.

## P1 — Instant play, stop the worst bugs

Tasks: P1-01 lean resolver · P1-02 stream first, limits only for keeping, fault flags · P1-03 two pools + YouTube pacing/back-off ·
P1-04 prepare (top result, page, queue) · P1-05 imported songs use their known video id · P1-06 measurement spans + harness ·
P1-07 search: Top result and one list · P1-08 the player never gets stuck · P1-09 offline without skipping (one calm strip, no permanent banner) ·
P1-10 covers everywhere, offline too · P1-11 resume after a hard kill; media-session position · P1-12 accessibility, insets, big
text, device-profile tests, small UX fixes · P1-13 one volume, consistent loudness · P1-14 stop the sync storm.
**Old phase exit (history; the items enforce it now):** journeys J-02, J-03 (owned part), J-06, J-07, J-08, J-10, J-11 pass on profiles A and B on TYPICAL; J-02 also on SLOW
within the hard limits; no S1 open in the player, search, offline or covers.

## P2 — Songs as references (the new library)

Tasks: P2-01 Encore server skeleton + song refs + library API · P2-02 the app's data layer on song refs · P2-03 play ≠ save,
keep-on-save and keep-on-repeat, albums/playlists play through catalogue songs · P2-04 imports in seconds · P2-05 import stop,
progress, consistent counts · P2-06 Spotify beyond 100 songs · P2-07 remove homelab portal code and the second import screen ·
P2-08 playback state and resume anywhere · P2-09 one device at a time · P2-10 invite-first sign-in and "Bring your music" ·
P2-11 migrate today's installs · P2-12 catalogue: search, matching, duplicates · P2-13 downloads, formats, manifest ·
P2-14 lyrics on the server · P2-15 notifications without push · P2-16 self-describing, self-healing library ·
P2-17 "Follow the original" playlists · P2-18 a changed or expired login is a normal event · P2-19 find your server (a key, the server's own addresses, a first screen without an IP address) · P2-20 Encore mode: the app holds only the device token. Design: `17`, `18`, `19`, `23`, `26`.
**Old phase exit (history; the items enforce it now):** J-01, J-03, J-04, J-05, J-09, J-12 pass; a like on a catalogue song survives the song being kept, re-tagged and moved
(integration test); migration from an existing install keeps every like and playlist (test on a copy of CT 104's database).

## P3 — One server, one-command install

Tasks: P3-01 people, sources, keeper, admin moved into the Encore server; the gateway as the only door · P3-02 published multi-arch
images · P3-03 device tokens, the gateway signs requests to Navidrome, one-way mirror · P3-04 remove Docker-socket control, Firefox,
Google sign-in · P3-05 install script, `encore.local`, `encore` CLI · P3-06 setup wizard and admin pages · P3-07 clean-machine proof ·
P3-08 updates with rollback, yt-dlp freshness, backups, moving computers · P3-09 security and privacy as written ·
P3-10 devices, settings and the Host's safety nets · P3-11 the Tinkerer's door · P3-12 the first outside user. Design: `15`, `21`, `22`, `26`.
**Old phase exit (history; the items enforce it now):** J-14 passes on a fresh Ubuntu 26.04 VM (x86) and on an ARM64 machine or VM, in ≤ 15 min; one published port; the admin
Health page explains every state in plain words.
**Split (D-53, owner 2026-11-03):** the x86 install is proved (`evidence/c01`, `c06`) and what the first outside user needs from P3 comes first; the ARM64 proof and the admin Health page (P3-06, the browser setup wizard and admin pages, PC-only) come later, after Jam and Discover. The first friends use the terminal installer and the app.

## P4 — Full feature set

Tasks: P4-01 listening profile and recommendations per person · P4-02 Jam on the live channel · P4-03 friend activity ·
P4-04 quality tier on song refs · P4-05 Year in Music from the server's play history · P4-06 the whole app walked again ·
P4-07 Encore Connect (devices, handover, remote volume) · P4-08 home-server relay (the app only talks to its own server) ·
P4-09 connecting with people on other servers (federation core) · P4-10 Jam across servers, sharing, collaborative playlists · P4-11 tablets and large screens (parked, D-18) ·
P4-12 Spotify-class extras · P4-13 problem reports and battery-saver guidance · P4-14 "Wrong song?" and metadata fixes · P4-15 Browse, history and playlist details · P4-16 profiles on a shared device · P4-17 compare tastes (US-65, opt-in).
Design: `13`, `14`, `16`, `19`, `20`.
**Order (D-53, owner 2026-11-03; wording corrected after the order analysis): Jam (P4-02) goes first among the features and ahead of P3-06.** Its prerequisites are the device model (P2-08, P2-09) and a public address walked on mobile data (check 2 of P3-12). The catalogue, lyrics and find-my-server work run in parallel and are not prerequisites. Discover (P4-01, with smart shuffle and "Not for me") follows it.
**Decided (advisor, 2026-11-01, reversible, D-48 a): D-18 holds everywhere.** Tablet-specific layouts are parked: P4-11 stays in `tasks/P4-full-feature-set.md` marked parked and is listed in `tasks/P6-later.md`; `03`, `03a` US-75, `14` U1 and ADR-R42 point 5 say so. The phone layout scales on a large screen (Android 16 shows it stretched anyway, `14` U1) until a tablet layout is asked for.
**Old phase exit (history; the items enforce it now):** US-60 … US-64 and US-70 … US-76 pass as journeys (incl. J-15 … J-20 of `14` section 3) on profiles A and B with two people on two emulators; recommendations judged by the owner
on his own account after a week of listening ("does Home know me?"); the quality tier upgrades a kept song on the dev VM without
moving any like, playlist entry or resume position.

## P5 — Public release

Tasks: P5-01 release signing key and CI signing · P5-02 in-app update check · P5-03 full device matrix + 5-day field test (owner +
one friend) · P5-04 cold start ≤ 0.7 s mid-range · P5-05 website, name, legal texts (**when the owner wants**; not now) ·
P5-06 go public (repo, images, first release) · P5-07 Android developer verification and the install guide (parked, D-17) · P5-08 what's new and in-app help.
**Old phase exit (history; the items enforce it now):** every promise N1–N11 (`03` §4) measured on SLOW and TYPICAL and on two real phones; the owner does not open Spotify for
5 days.

## P6 — Later

iOS · web/desktop client (the API is ready from P2) · casting to Chromecast/TV speakers · localisation (French, Arabic first) ·
flashable "Encore OS" image (if Hosts struggle to install Linux).

## Rough size and parallelism

**Superseded (2026-11-03):** these numbers were never recalibrated. The calibrated method is in "How long" at the top of this file, and every item's range is in the generated list.

| Topic | Parallel lanes | Rough effort |
|-------|----------------|--------------|
| P0 | 2 (repo/GitHub; CI) | 1–2 days |
| P1 | 3 (server resolver P1-01..05; player/offline P1-08..11; UI/search/a11y P1-07, P1-12) | 4–6 days |
| P2 | 2 (server P2-01, P2-04, P2-08/09; app P2-02, P2-03, P2-10) | 8–12 days |
| P3 | 2 (server consolidation; install/wizard) | 6–8 days |
| P4 | 4 (recommendations + extras; devices + accounts; federation + Jam + friends; quality tier + Year in Music; tablet parked) | 25–35 days |
| P5 | 2 | 4–6 days + 5-day field test |
