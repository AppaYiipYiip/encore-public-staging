# 08 — Roadmap

> **In short.** The plan explained: one flat list (Now) and Later, how an item's needs and a drag work, what "done" means (walked as a person on the release-candidate pair, otherwise "built, not walked"), why the list is in this order and how the estimate is computed. The list inside it is generated from `docs/roadmap/` by `tools/check_order.py --write`; never edit it by hand.

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

* **Claude marks** an item with `python tools/roadmap.py mark ITEM built|walked --evidence "..."` in the PR of the work. `walked` refuses a missing proof, takes the item out of `order.json` in the same step, regenerates the lists in this file in that same step (so there is no second command and no stale-list failure in CI), and cites the owner's own check when there is one.
* **The owner's buttons never prove an engineering item** (he is not the tester): *I did this* only on an item that needs him (protect `main`, the keystore): his word is the proof; *I checked it* only where his own judgement is part of the acceptance (`judge`): recorded, cited when Claude proves the item; *It doesn't work* on anything built or done: it reopens the item at the front of the list (never before something it needs) and leaves Claude a note waiting; *Not done after all* takes a check back. They write **notes**, and the state shown is derived from `status.json` plus those notes, so `status.json` keeps one writer.

### Why the list is in this order

* **Gates first (D-61).** The owner's three thresholds are pink items: P0-14 (he tries the app), P3-18 (he installs by clicking), P3-24 (he invites his friend and they jam). Everything the friend-ready list needs is a need of P3-24, so the order of the list is the order of the road.
* **Notification when an artist you follow releases something** has three parts: the server's daily check (P2-15, it replaces the phone calling Deezer), the follow and the shelf (P4-18) and the phone notification, which stays **opt-in** (ADR-R44; D-52 allows the one exception for download progress only).
* **"Not for me"** is part of P4-01 (`POST recs/feedback`, `17`): a person's dislike changes only that person's rows.
* **Design before building, on Android first** (D-43): the phone's drawings exist; the large-screen drawings are the first large-screen task (P6-01), drawn by the planning agent and approved by the owner before any code. The browser is built from the same Flutter code (D-55), so the tablet and the TV reuse its layouts later (D-58).
* **The iPhone is last, and it is the only item whose feasibility is decided outside the project.** The app is distributed on GitHub only (D-56): there is no App Store or TestFlight, so an iPhone version can only be installed by sideloading, which P6-04 verifies before any code; a "no" is a result, not a delay.

The conditions of the twelve phases the first draft had (history, D-57), and the sweep of 3 Nov that found the tasks P0-11 to P0-13, P1-15, P2-23, P3-14 to P3-16, P4-18 and P6-01 to P6-07, are in git (`git show a7693a2:docs/08-roadmap.md`); every condition that mattered now sits on the item it constrains.

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

**The plan, in order** (one list, top = next): 124 items still to do, 12 of them built and waiting for a walk, 26 done. About 317.5 Claude-days of work left, so roughly **93 to 187 working days** (about 19 to 37 weeks) elapsed in all (external waits and the owner's own steps are not in it). A range from a stated method, never a date. `*` marks a policy need (a rule the project chose, which the owner may override).

| # | Item | What | Size | State | Needs | Ready around working day |
|---|------|------|------|-------|-------|--------------------------|
| 1 | N-19 | Pausing a downloaded song while offline no longer says there is no connection | S | todo | none | 1 to 2 |
| 2 | N-20 | A downloaded song starts playing the moment you tap it, also offline | M | built | none | 1 to 1 |
| 3 | N-11 | One song is one entry on your phone, not two (fixes missing covers and artist lists) | M | todo | none | 3 to 4 |
| 4 | N-21 | The top search result has the same three buttons as every other song | S | built | none | 1 to 3 |
| 5 | N-22 | Tapping the open tab again returns to that tab's first page (Home, Search, Your Library) | S | built | none | 2 to 3 |
| 6 | P1-07 | Search shows one clear best result at the top | M | todo | none | 3 to 5 |
| 7 | N-23 | Search finds the band even when a letter or two is wrong | M | todo | none | 3 to 7 |
| 8 | N-24 | Listen to one artist without picking albums: Play all and Shuffle on an artist | M | built | none | 4 to 7 |
| 9 | N-25 | Search inside a playlist | M | built | none | 4 to 8 |
| 10 | P1-26 | An imported song without a picture shows YouTube's thumbnail, not a letter | S | built | none | 4 to 8 |
| 11 | P1-10 | Covers show everywhere, also when you are offline | M | todo | P1-26 | 5 to 9 |
| 12 | P4-24 | One Data saver switch for slow or metered connections | S | built | none | 5 to 10 |
| 13 | P0-16 | Make GitHub's checks run again (the allowance is used up, so nothing can be merged) | S | todo | none | 5 to 10 |
| 14 | P1-02 | Playing starts first; size limits only apply when you keep a song | M | built | none | 5 to 10 |
| 15 | N-14 | Behind the scenes: find why an artist page sometimes waits two seconds | S | todo | none | 5 to 11 |
| 16 | P1-08 | The player never gets stuck | M | built | none | 6 to 11 |
| 17 | N-13 | Search marks the songs your server cannot find, and the server remembers it | S | todo | none | 6 to 12 |
| 18 | P1-24 | A Share button on the full player | S | built | P1-22 | 6 to 12 |
| 19 | P1-17 | Behind the scenes: one "can I reach my server" state in the app instead of eleven | L | todo | none | 8 to 16 |
| 20 | P1-16 | Search says when you are offline (drawn first) | S | todo | P1-15, P1-17 | 8 to 16 |
| 21 | N-17 | After "Rebuild library" your music shows again at once, and "Last sync" tells the truth | S | todo | none | 9 to 17 |
| 22 | N-10 | Songs by several artists are saved with each artist on its own | M | todo | none | 9 to 19 |
| 23 | N-12 | "Go to artist" in a song's menu offers every artist of the song | S | todo | none | 10 to 19 |
| 24 | N-15 | Artists the music server has no picture for get one | S | todo | none | 10 to 20 |
| 25 | P2-25 | Behind the scenes: songs in Arabic, Russian, Korean and Japanese are told apart and found | M | todo | none | 11 to 22 |
| 26 | P2-12 | Search and artist pages come from your own server | L | todo | none | 13 to 26 |
| 27 | P2-15 | Your server checks for new releases; the news shows in the app | S | todo | P2-12 | 13 to 26 |
| 28 | P4-18 | Follow artists, and get told when one releases something | S | todo | P2-15 | 14 to 27 |
| 29 | P2-26 | Behind the scenes: a short YouTube hiccup no longer fails a song for good | S | todo | none | 14 to 28 |
| 30 | N-16 | Behind the scenes: 40 real searches prove the right song is picked | M | todo | P2-25 | 15 to 29 |
| 31 | P2-29 | One notification for the whole download while the server is still saving | M | todo | none | 16 to 31 |
| 32 | P2-22 | A download shows where it is: progress, a notification, and why if it stops | M | built | P1-17, P2-29 | 16 to 32 |
| 33 | P3-01 | Behind the scenes: the whole server is one program | L | built | none | 16 to 33 |
| 34 | P5-01 | Make your release key (so updates never force a reinstall) | S | todo | none | 16 to 33 |
| 35 | P1-18 | Check on a real phone: calls, headphones, a full phone and a long pause | M | todo | none | 17 to 34 |
| 36 | P1-19 | Behind the scenes: every request carries an id so a failure can be followed | S | todo | none | 18 to 35 |
| 37 | P3-35 | New music shows up in the app within minutes | S | todo | none | 18 to 36 |
| 38 | P2-28 | An edit that is still waiting is never undone on the screen | S | todo | none | 18 to 36 |
| 39 | P0-13 | Before your first friend: Claude checks everything built so far, like a real user | M | todo | P1-01, P1-02, P1-05, P1-06, P1-08, P1-11, P2-02, P2-03, P3-01, P3-04, P1-15, P1-16, P2-22, P5-01, P1-18, P1-19, P2-25, P2-26, P1-21, P3-35, P2-28, N-16 | 19 to 38 |
| 40 | P0-14 | Gate 1: you try the app on your own phone | S | todo | P0-13, P5-01, P1-04, P1-10, P1-16, P2-22 | 19 to 38 |
| 41 | P3-28 | Behind the scenes: measure the away-from-home address with real music (it already works on your phone) | S | todo | none | 19 to 39 |
| 42 | N-18 | Behind the scenes: turning on the away-from-home address also works over a plain ssh session | S | todo | none | 20 to 39 |
| 43 | P3-26 | Where the server and the app come from while the code is still private (designed first) | S | todo | none | 20 to 40 |
| 44 | P3-29 | Behind the scenes: server hygiene, so one slow request or one hiccup cannot hurt everyone | L | todo | none | 22 to 44 |
| 45 | P3-31 | Behind the scenes: split the one big server file into one file per area | M | todo | P3-29 | 23 to 46 |
| 46 | P3-32 | Behind the scenes: a big import no longer makes a friend's small one wait for hours | S | todo | none | 23 to 46 |
| 47 | P3-33 | Behind the scenes: a music disk that is briefly missing no longer wipes the library link | S | todo | none | 23 to 47 |
| 48 | P3-30 | Behind the scenes: set a password key at install, and make backups secret | M | todo | none | 24 to 49 |
| 49 | P3-20 | Add-ons: built in, bring your own, or off (designed on paper first) | M | todo | none | 25 to 50 |
| 50 | P3-21 | Two doors to the same installation: the button installer and the command (designed on paper first) | M | todo | P3-28, P3-26 | 26 to 52 |
| 51 | P3-22 | Change the drawn setup pages for the new rules, approved by you | S | todo | P3-20, P3-21 | 26 to 53 |
| 52 | P3-25 | Behind the scenes: a small helper on the server computer for the buttons and the command | M | todo | P3-21 | 27 to 54 |
| 53 | P3-27 | Behind the scenes: a release channel that only moves when someone decides | M | todo | P5-01 | 28 to 56 |
| 54 | P2-24 | Behind the scenes: the app and the server tell each other their versions | S | todo | P3-27 | 28 to 57 |
| 55 | P2-27 | After a restore, phones and server agree again | M | todo | none | 29 to 59 |
| 56 | P3-14 | Server updates that undo themselves: a button, and a command | M | todo | P3-25, P3-27, P3-30, P2-24, P2-27 | 30 to 60 |
| 57 | P3-16 | Reset a forgotten password: a button, and a command | S | todo | P3-25, P3-21 | 30 to 61 |
| 58 | N-05 | Back up your music files to another place, with a button | S | todo | P3-25, P3-20 | 31 to 61 |
| 59 | P3-11 | Use a music server you already run (for people who like tinkering) | M | todo | none | 32 to 63 |
| 60 | P3-23 | Build the button installer | L | todo | P3-21, P3-02, P3-25, P3-27, P3-26 | 34 to 67 |
| 61 | P3-06 | The setup pages and admin pages in the browser, with a button for everything | L | todo | P3-22, P3-20, P3-25, P3-21 | 36 to 71 |
| 62 | P3-07 | Proof that a fresh computer installs the server from the guide, also on a slow line | S | todo | P3-02, P3-23 | 36 to 72 |
| 63 | P3-18 | Gate 2: you install your real server yourself, by clicking | S | todo | P3-05, P3-22, P3-06, P3-23, P3-07, P3-11, P3-25, N-05, P3-16, P3-14, P3-26, P3-29, P3-30, P3-27, P3-33 | 36 to 72 |
| 64 | P1-20 | Behind the scenes: every word the app shows lives in one place | M | todo | none | 37 to 74 |
| 65 | P3-03 | Behind the scenes: each phone gets its own key to the server | M | todo | none | 38 to 76 |
| 66 | P2-14 | Lyrics come from your own server | S | todo | none | 38 to 76 |
| 67 | P2-23 | Behind the scenes: one written rulebook that every app and the server follow | M | todo | none | 39 to 78 |
| 68 | P2-20 | Behind the scenes: the app keeps only a device key, not your music server password | L | todo | P2-12, P2-14, P3-03, P2-15* | 41 to 82 |
| 69 | P2-19 | The app finds your server without typing an address | L | todo | P2-20 | 43 to 86 |
| 70 | P2-10 | Sign in by invitation, and bring your own music | M | todo | P2-19 | 44 to 88 |
| 71 | P3-10 | Add a device with a QR code; settings follow you; cancel a lost device | M | todo | P2-19 | 45 to 90 |
| 72 | P2-08 | Pick up where you left off on another device | M | todo | none | 46 to 91 |
| 73 | P2-09 | One device plays at a time, like Spotify | M | todo | P2-08 | 47 to 93 |
| 74 | P5-07 | The install guide for your friend: how to install the app from GitHub | S | todo | P5-01 | 47 to 94 |
| 75 | P6-01 | Drawings of the browser version, approved by you before any code | S | todo | none | 47 to 94 |
| 76 | P6-02 | The browser version: the same app in any desktop browser | L | todo | P6-01, P2-19, P2-23*, P2-20, P2-12, P2-14 | 49 to 99 |
| 77 | P4-23 | Crossfade between songs, with gapless kept | L | todo | none | 51 to 103 |
| 78 | P4-02 | Jam: listen together | L | todo | P2-08, P2-09, P3-18*, P3-28, P4-23* | 53 to 107 |
| 79 | P4-12 | Android Auto: browse your music and play by voice from the car screen | S | todo | none | 54 to 107 |
| 80 | P4-22 | A home-screen widget: what is playing, with play, pause and next | M | todo | none | 55 to 109 |
| 81 | P4-04 | Optional lossless (CD-quality) audio | L | todo | none | 57 to 113 |
| 82 | P4-20 | Behind the scenes: choose how suggestions are made, a ready-made engine or our own | S | todo | P2-12 | 57 to 114 |
| 83 | P4-01 | A Home made for you: suggestions, smart shuffle, radio and "Not for me" | L | todo | P2-12, P4-20, P4-23* | 59 to 118 |
| 84 | P4-05 | Your Year in Music, from what you really played | S | todo | none | 59 to 119 |
| 85 | P4-07 | Control one device from another, with remote volume | L | todo | P2-08, P2-09, P4-23* | 61 to 123 |
| 86 | P0-10 | Behind the scenes: check that every library we use may legally be used | S | todo | none | 62 to 123 |
| 87 | P2-18 | A changed or expired sign-in is handled calmly | M | todo | P3-03 | 63 to 125 |
| 88 | P3-13 | You set a storage limit and a biggest-song limit; the server says when it is full | M | todo | none | 63 to 127 |
| 89 | P3-34 | Behind the scenes: the music server's own door stays shut to visitors | M | todo | none | 64 to 129 |
| 90 | P3-15 | Before your first friend: a security check of everything reachable from the internet | M | todo | P3-29, P3-30, P3-34 | 65 to 130 |
| 91 | P3-19 | Start Claude's deep security review before your first friend (one command, it costs money) | S | todo | P3-15 | 65 to 130 |
| 92 | P3-24 | Gate 3: you invite your friend and jam with him | S | todo | P3-18, P5-07, P4-02, P6-02, P2-10, P2-19, P3-10, P2-08, P2-09, P4-12, P4-22, P4-23, P4-24, P4-04, P4-01, P2-14, P4-05, P4-07, P3-15, P3-19, P3-26, P3-28, P2-24, P3-29, P3-30, P3-32, P0-10, P2-18, P3-13 | 65 to 130 |
| 93 | P3-12 | Your friend's first week on your server | M | todo | P3-05, P3-24 | 66 to 132 |
| 94 | P4-21 | Library polish: search aliases, sort and filter, pins and folders, custom covers | M | todo | none | 67 to 134 |
| 95 | P2-05 | Importing has a stop button, shows progress and counts correctly | S | todo | none | 67 to 134 |
| 96 | P2-07 | Behind the scenes: remove leftover old code and a duplicate import screen | S | todo | none | 68 to 135 |
| 97 | P2-13 | Downloads in the right format; stale files get replaced | M | todo | none | 68 to 137 |
| 98 | P2-21 | Playlist description and picture; select many songs at once | M | todo | none | 69 to 139 |
| 99 | P2-06 | Spotify import works beyond 100 songs and brings your Liked Songs | M | todo | none | 70 to 140 |
| 100 | P2-17 | Imported playlists can follow the original playlist | M | todo | none | 71 to 142 |
| 101 | P4-15 | Browse, history and playlist details | M | todo | P2-17 | 72 to 144 |
| 102 | P0-09 | Behind the scenes: one command starts a full test setup on any computer | M | todo | none | 73 to 146 |
| 103 | P2-16 | Behind the scenes: your library repairs itself after a restore | M | todo | none | 74 to 147 |
| 104 | P3-08 | Move the server to another computer, see statistics, and test restores every night | L | todo | P3-14 | 76 to 151 |
| 105 | P3-09 | Privacy rules tested; export your data; delete your account | M | todo | none | 77 to 153 |
| 106 | P4-03 | See what your friends listen to (only if they agree) | M | todo | none | 78 to 155 |
| 107 | P4-19 | Start Claude's deep security review of friends on other servers (one command, it costs money) | S | todo | none | 78 to 155 |
| 108 | P4-09 | Friends on other servers | L | todo | P0-09, P4-03, P4-19 | 80 to 159 |
| 109 | P4-08 | Behind the scenes: your phone only ever talks to your own server, even for friends' servers | M | todo | P4-09 | 80 to 161 |
| 110 | P4-10 | Jam across servers, sharing, and shared playlists | L | todo | P4-02, P4-09 | 83 to 165 |
| 111 | P4-17 | Compare music taste with a friend (only if they agree) | M | todo | P4-09 | 83 to 167 |
| 112 | P4-14 | "Wrong song?" fix, and editing song details | M | todo | P2-12 | 84 to 169 |
| 113 | P1-12 | Big text, right-to-left languages and screen readers work | L | todo | P1-20 | 86 to 173 |
| 114 | P1-14 | Less syncing, so less battery and mobile data | S | todo | none | 87 to 173 |
| 115 | P4-06 | Before the public release: Claude walks the whole app again like a real user | M | todo | P4-02*, P4-07*, P4-09*, P4-10*, P4-01*, P4-04*, P6-02* | 88 to 175 |
| 116 | P5-02 | The app checks for updates by itself | S | todo | P5-01 | 88 to 176 |
| 117 | P5-03 | Claude tests on many phones, and you use the app without Spotify for 5 days | M+5 | todo | P4-06* | 90 to 180 |
| 118 | P5-04 | The app opens in under 0.7 seconds | M | todo | none | 91 to 182 |
| 119 | P5-09 | Start Claude's deep security review before going public (one command, it costs money) | S | todo | P5-03 | 91 to 182 |
| 120 | P5-06 | Make the code public on GitHub and publish the first release | S | todo | P5-03, P5-09, P0-10, P0-12, P3-09 | 91 to 182 |
| 121 | P5-08 | A "what's new" screen and help inside the app | S | todo | none | 91 to 183 |
| 122 | N-09 | A first-run experience that feels designed | M | todo | none | 92 to 184 |
| 123 | N-01 | Share a song, album or playlist as a link | M | todo | none | 93 to 186 |
| 124 | N-02 | Export a playlist as a file | S | todo | none | 93 to 187 |

**Later** (21 items: future work to keep in mind and not bother with now, D-58; no estimate)

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
| P2-11 | Behind the scenes: migrate old installs (closed: none exist) | L | none |
| P4-13 | Problem reports and battery-saver tips (shelved) | M | none |
| P5-05 | The website, the name and the legal texts | M | P3-07 |
| P1-13 | One volume and the same loudness for every song | M | none |
| N-07 | A better logo and app icon | S | none |
| N-08 | A fresh visual design for the phone app | L | none |
| P0-15 | Behind the scenes: a plugin the app uses will stop a future Flutter from building | S | none |
| P3-36 | Saving a playlist says how long is left, and the Host can change the pace | S | none |
| P3-37 | Behind the scenes: updating the server says what it did | S | none |

**Done** (26 items with their proof; what is left inside them is in `history/reviews-2026-10-31.md#audit`)

| Item | What | Proof |
|------|------|-------|
| P0-01 | Behind the scenes: secrets and old leftovers cleaned out of the code | README State: P0 done; gitleaks runs in CI |
| P0-06 | Behind the scenes: automatic checks run on every change | CI runs on every change (workflows app, server, docs, goldens, server-image) |
| P0-07 | Protect the main branch on GitHub (nobody can overwrite your code by accident) | verified with gh api on 2026-11-04: ruleset 'protect main' (id 26569683) is active on the default branch, no bypass; blocks deletion and force push; a pull request is required (0 approvals); checks 'checks' and 'secrets' must pass |
| P0-08 | Behind the scenes: written rules so every Claude works the same way | AGENTS.md and docs/30 exist and the pre-commit hook enforces them |
| P0-11 | Behind the scenes: keep the automatic checks and build tools up to date | 7 Nov 2026, docs/evidence/README.md#e03: the newest completed run of App, Hygiene, Server image, Server and Server legacy on main has 0 annotations; today's Goldens run (after the upgrade) 0; Dependabot Updates carries only GitHub's own ubuntu-latest notice; main is protected; both release APKs (x64, arm64) build on the upgraded toolchain. The Kotlin plugin warning is P0-15. |
| P0-12 | Behind the scenes: fix the places where the documents promise more than the app does | 7 Nov 2026, docs/evidence/README.md#e03: the install guide followed on the clean VM (image 9c09a7a): exit 0 in 11 min 12 s, the questions in the order of the guide's table; the line that promised more than it did was reworded in #205 (read in install.sh, not re-run). |
| P1-01 | Songs you do not own start playing in about 2 seconds | docs/evidence e03: J-02 on the release-candidate pair, 13 never-played songs, median 2.14 s, p95 and slowest 2.60 s, song found in 0.4 to 0.9 s and address in 0.7 to 1.1 s, 3 look-ups a song; server/encore_server/tests/sources/test_lean.py makes subprocess.run and Popen fail on the lean path. The labelled set of 40 searches was split off as N-16 on 7 Nov 2026 and P0-13 needs it. |
| P1-03 | Behind the scenes: YouTube is asked gently, so your home address is never blocked | the 217-song YouTube import fetched through VM 108 in about 46 minutes with no refusal (build 125 pair, 3 Nov 2026; AUDIT round 2) |
| P1-04 | The next songs are prepared before you tap them | 7 Nov 2026, docs/evidence/README.md#e05: pair 4 (image ee121c1 + build 136 from the same commit). Next to a song the server prepared: median 640 ms on the owner's A35 (9 changes, 373-1148 ms, eight of nine under 1 s) and about 830 ms on emulator B (12-song album 626-1173 ms; a 10-song run median 888 ms); before the fix 2399 and 2380 ms. Seven of 35 changes measured were over 1 s (max 1551 ms), so 'each change under 1 s' is NOT met; the owner saw the numbers and accepted them. Rapid skipping (a Next every 2 s) stays slow for unprepared songs (1820, 4335 ms). |
| P1-05 | Imported playlists play the same video they came with | 7 Nov 2026, docs/evidence/README.md#e03: pair: server image 579dfea (VM 108; updated from the clean install of 9c09a7a) + APK build 131 from the same commit, emulators B and A and the owner's Samsung A35. All 154 per-song search jobs date from the first import (before #210); the second import (189 songs) created none; an imported song that is not saved ('Roc The Mic') was audible in 2.24 s with the server saying 'the song found in 0.0 s' and one look-up. |
| P1-06 | Behind the scenes: tools that measure how fast the app really feels | docs/evidence e03 (tools/journeys/play_timing.py reads the app's own [perf] span play.audible on the release-candidate pair: 13 songs) and e05 (tools/journeys/next_timing.py: on build 134 a Next read 2399 and 2380 ms, on build 136 after the P1-04 fix 1003, 819 and 641 ms, other fresh albums; the first tap did not get faster: 3089 against 4123 ms). The scratchpad probe of e04 that counted the media session's PLAYING was withdrawn in #223 and is not part of this item. The request-id half is P1-19 (audit B-32), still to do; the unrunnable build-40 check was dropped on 7 Nov 2026 with its reason written in the task. |
| P1-09 | Offline: no skipping, greyed-out songs, and it recovers by itself | round 2 on build 125 against VM 108 (3 Nov 2026): a downloaded song plays offline, a row that is not downloaded says so (ROUND2-LOG) |
| P1-11 | Playback resumes after the phone closes the app, with the right lock-screen position | 7 Nov 2026, docs/evidence/README.md#e03: pair: server image 579dfea (VM 108; updated from the clean install of 9c09a7a) + APK build 131 from the same commit, emulators B and A and the owner's Samsung A35. Force-stop then reopen: an owned song (paused at 2:34, playing at 2:42, seek while playing 0:55) and a streamed catalogue song (1:31) came back paused at the same second; after a full emulator reboot 0:54 came back as 0:54; on the real A35 a seek to 2:19 came back paused at 2:19. The reboot and the lock-screen widget were not done on the A35 (PIN, unlocked phone). |
| P1-15 | The app tells you when you are offline | 7 Nov 2026, docs/evidence/README.md#e04: pair 2: server image 586bbba (VM 108) + APK build 132 from the same commit (build 133 from 620cbe8 for the lyrics recheck), emulators B and A and the owner's Samsung A35, emulator B. Airplane: no strip at +2 s, 'You're offline. Downloaded music still plays.' at +7 s, gone by +16 s, rows named 'not downloaded', a tap says 'Not downloaded. Connect to play it.', all gone by themselves after the network came back; stopped server: 'Can't reach your server.' at +2.2 s, a tap says 'Not downloaded. Can't reach your server.', gone 2.1 s after the server was back. The real phone and a network with no internet behind its Wi-Fi were not used. |
| P1-21 | Playing a finished list again works, and the player never says playing while it is silent | 7 Nov 2026, docs/evidence/README.md#e03: pair: server image 579dfea (VM 108; updated from the clean install of 9c09a7a) + APK build 131 from the same commit, emulators B and A and the owner's Samsung A35. On the A35 all five ways of pressing Play after a finished list (page Play, Shuffle, mini player, full player, media key) restarted the list and played it to its end; 162 of 164 PLAYING samples had real audio, the other 2 are in the last second of a list. Lock-screen widget not re-walked on build 131 (phone must stay unlocked). |
| P1-22 | The full player uses the whole screen: no empty area below the controls | 7 Nov 2026, docs/evidence/README.md#e04: pair 2: server image 586bbba (VM 108) + APK build 132 from the same commit (build 133 from 620cbe8 for the lyrics recheck), emulators B and A and the owner's Samsung A35. On the A35 the cover and controls spread over the full height and the seek bar, Play, Share and queue sit at the same rows for a song with and without lyrics; on the small profile-A phone the page scrolls and the bottom row and the card are reachable; widget tests at four phone shapes. The owner's own word on whether it is better is his. |
| P1-23 | The Lyrics card shows at the bottom of the full player | 7 Nov 2026, docs/evidence/README.md#e04: pair 2: server image 586bbba (VM 108) + APK build 132 from the same commit (build 133 from 620cbe8 for the lyrics recheck), emulators B and A and the owner's Samsung A35. The Lyrics card is always there at the same place and size (A35: same pixel rows with and without lyrics); a streamed song that is not saved shows its synced lyrics; Opeth 'Benighted' on the owner's A35 with build 133: 'Lyrics' (synced), a normal apostrophe, and a tap on a line jumped the song to it (1:37). |
| P1-25 | The full player shows which device the sound comes out of, and lets you change it | 7 Nov 2026, docs/evidence/README.md#e06: on the owner's Samsung A35 (build 136 arm64, pair 4: image ee121c1 + the same commit) with his Bluetooth speaker 'soundcore Sport X20' connected, the full player's output row reads 'soundcore Sport X20' with a Bluetooth icon and the Devices sheet ticks it ('The sound is playing here') with 'Choose another sound output' and 'Your other devices: not built yet' (pictures). A wired output was not connected. |
| P1-27 | Songs always play in full: the 30-second preview is removed | 7 Nov 2026, docs/evidence/README.md#e04: pair 2: server image 586bbba (VM 108) + APK build 132 from the same commit (build 133 from 620cbe8 for the lyrics recheck), emulators B and A and the owner's Samsung A35. A tap and a long-press on a Search row, a tap on an album row and on an artist's popular song each played the whole song (3:22, 2:59, 3:38); no screen said 'Preview'; a streamed song that is not saved showed its lyrics. |
| P2-01 | Behind the scenes: the server's core, where a song is one entry whoever owns it | installed by the guide on a bare VM (evidence/c06); signed in, invited and imported against it in round 2 on build 125 (3 Nov 2026) |
| P2-02 | Behind the scenes: the app's database rebuilt around songs as entries | 7 Nov 2026, docs/evidence/README.md#e03: pair: server image 579dfea (VM 108; updated from the clean install of 9c09a7a) + APK build 131 from the same commit, emulators B and A and the owner's Samsung A35. A like made on one emulator showed on the other, same account, in 1.29 s (unlike and like again; the figure includes the poll). The upgrade: build 40 over its own database on the A35, then 130, then 131: the playlist 'Upgrade test' with its song and the liked songs are still there on the A35 and the emulators. |
| P2-03 | Playing something is not saving it; albums play even for songs you do not own | 7 Nov 2026, docs/evidence/README.md#e04 and #e05: playing is not saving: the music server's library did not change after 13 streamed songs (e04) nor after a 13-song catalogue album played to its end with Next 12 times (395 songs before and after, e05); all 13 songs in order, Next enabled throughout, one song of the album already kept by the server played in the same run; a liked streamed song showed in Liked Songs at once and the server kept it (e04). Not walked: the 'played on 2 different days is kept' clock (a unit test, test_keep_triggers.py) and 'two people keeping one song make one file' (unit tests). |
| P2-04 | Import a playlist in seconds | the owner imported two playlists (4 and 217 songs) on build 125 against VM 108 (3 Nov 2026) |
| P3-02 | Behind the scenes: the server packaged for Intel and AMD computers | docs/evidence c01 (installer on a clean VM, the image pulled from the registry, five runs), c03, c06 (the guide on a bare VM, image :main), e03 (VM 108 updated with encore update on the release-candidate pair: 4.2 MB of code layers); measured 7 Nov 2026 from the registry's own manifest: amd64, 14 layers, 243.9 MB over the wire (the limit is 450 MB). 'Compose uses pinned tags' moved to P3-27 the same day. |
| P3-04 | Behind the scenes: risky leftovers removed (full control of the server computer, Firefox and Google sign-in) | 7 Nov 2026, docs/evidence/README.md#e03: on the running VM: two containers, one published port (4533 on the Encore container), no docker.sock in the compose file or any mount, no browser in the image. |
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
