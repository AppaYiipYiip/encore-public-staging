# 30 — Engineering guide: what to do, what not to do, and how we know

For everyone who writes or reviews code here, person or agent, **especially someone who starts with no memory of the earlier sessions**
(a new account, a new agent, a new contributor). The owner reads the quality of the code as the product's first impression and wants it kept.

> **The owner's standing rule** (he has had to repeat it in every session; it applies by default and is never news). Do not consider, choose or suggest the easy option that fixes the problem now but costs **upgradeability, improvement or compatibility** later. Spend the time to engineer the proper answer first: the root cause with proof, the fix at the source, a defensive layer only as a *second* layer that stays correct afterwards. When a stop-gap is truly unavoidable, say so, say what it costs later, and give it a removal trigger, a task for the proper fix and a visible reminder. Never offer "leave it as it is" as an equal option next to the proper one.

Most *Don'ts* below are something that **actually happened here** (the finding ID, such as A2 or C3, is in brackets and is explained in `01` with the evidence); the rest are guards
for things that would hurt if they happened (secrets in logs, an unsafe migration). Every *Do* is what the repository does now, or the next step where it says so. The last column
says what catches a violation:

* **Machine** = a command or a CI job fails (`tools/check.ps1`, the pre-commit hook, GitHub workflows).
* **Convention** = nothing checks it except you and the reviewer. **Keep those rows in your head; they are the ones that decay.**
  Until branch protection on `main` is switched on (P0-07, open), "pull request and review" is also a convention.

Other files this one leans on, not repeats: `AGENTS.md` (the do/don't list), `06` (how a change travels), `07` (how to test and what a measurement must say),
`04` (the architecture), `28` (the code, module by module), `11` (the decisions).

---

## 0. Before you write a line: ten questions (answer them in the pull request; if you cannot, stop)

1. **Which story (`03a`) and which promise (`03` §4) does this serve?** None: do not build it; write it as an idea on the board (the + button, or `roadmap.py note`).
2. **Does the core promise still hold** (a song you don't own: ~2 s typical, **≤ 10 s worst case**)? An open S1 bug in the area is fixed before new work there.
3. **Would a web, desktop or TV client get this for free?** Does every outside service (YouTube, Deezer, lyrics, covers) go through the server (ADR-R38)? If only the phone can do
   it, write down why it must.
4. **Where does it live?** One module, one folder. Does code for it already exist? Reuse it; never copy a function into a second place (the old repo had `navidrome.py` four times).
5. **What happens when it is slow, offline, refused, killed half-way, run twice, or run by two people at once?**
6. **How will I measure it, on which setup (`07` §2), and which number means done?**
7. **How will a person see it fail?** What does the screen say, in plain words, and what can they do?
8. **Is this hard to undo (a data shape, a public address, an API, a choice of library)?** Write an ADR with the options compared (`11`) and ask the strongest model
   you have **before you commit** (section 3).
9. **Which state table does this touch (`31` connecting, `32` accounts and devices, `33` playback, `34` conflicts)?** Change its row in the same pull request, with the test that covers it; a state or a failure that has no row is added before the code.
10. **Does this decide something another client would have to repeat, or need a platform part (ADR-R42)?** Ranking, merging, counting, what a section contains, who may do what: the server answers, the client draws. Could a browser do it with only HTTPS to its own server? What does a client without the platform part do? How does it work with a D-pad (a TV)? A decision that stays on the client says why in the pull request.

---

## 1. The rules

### A. Product and scope

| Don't (what happened) | Do | Caught by |
|-----------------------|----|-----------|
| Build side features while the core promise is broken (A2: Jam, an admin site, a quality tier, a recommender were built while a song took **38 s**) | Promise first. The roadmap order is the priority order; exit criteria are checked with evidence (`08`) | Convention |
| Change the plan's shape every day (A1: nine different plans in five days) | One plan (`docs/README.md`); the owner's decisions in `10`/`11`; stories in `03a`. No feature without a story (`06` §1) | Convention |
| Build for a hypothetical user (the in-app "Report a problem": built, walked, shelved, ADR-R35) | Ask who is hurt today. Park finished code on a branch (`parked/…`), write the idea down in the task | Convention |
| Build for one person's machines (A4: the app talked to the owner's private request portal) | Nothing about anybody's own network in code, docs or defaults. Design for other countries, weak PCs, flagged addresses, non-Latin text (`04` §6) | Convention; the secret and file checks catch some leaks |

### B. Architecture

| Don't (what happened) | Do | Caught by |
|-----------------------|----|-----------|
| **Let a client call an outside service itself** (today: the phone calls Deezer, LRCLIB and outside picture addresses; a browser cannot, and each call shows the person's own address) | **Clients talk only to their own Encore server; the server talks to the outside** (ADR-R38). Media elements use short-lived signed addresses. Native-only shortcuts are extras, never the only route | **Machine** for addresses written into the source (the outside-host ratchet in `app/test/architecture_test.dart`, section 5); **convention** for an address that arrives in data (a cover URL inside a record) |
| Many programs for one home server (C1: seven server programs, six ports, each with its own copy of the music-server client) | One program, modules in folders, one HTTP client, one auth check, one port (ADR-R3, `04` §2) | Convention; the old code is being removed (P3-04) |
| Make a file id the song's identity (C3: it led to "pending likes", an "instant playlist" and an "upgrade map", each a new way to lose a like) | A **song ref** is the identity; files attach to it; likes and playlist entries point to refs (ADR-R4, `18`) | Machine: the integration suite against a real music server (CI `encore-server-navidrome`); otherwise convention |
| Make the app find each service two ways (C2: by port at home, by path away) | One front door: the gateway; one base URL per server (`04` §2, §8) | Convention |
| Wrap the critical path for a niche feature (C8: the Jam wrapped every play) | Features are **layers** on the live channel; the player does not know they exist. Lower layers never import `features/` | Machine: architecture test (`core`, `data`, `domain`, `playback` do not import `features/`; `domain` is plain Dart) |
| Give a service root-like power, or ask for a person's accounts (C5: the Docker socket; C6: a Google account signed into the server) | Least privilege. No account of a person's on the server, ever. Unofficial sources sit behind one interface with a switch (ADR-R2) | Convention; the install proofs check what is published (`c01`) |
| Put passwords or login tokens in URLs, or keep the password on the phone (C9) | Device tokens in the `Authorization` header. The one exception is a short-lived **signed** address for a media element (`17` §1) | Machine for the signature (`tests/test_stream_route.py`); otherwise convention |
| Run work that nobody can stop or see | Work is rows in a queue with a kind, a priority and an owner; restart resumes it; Stop cancels it (`04` §10) | Machine: scheduler unit tests; convention for new work |

### C. The app (Dart)

| Don't (what happened) | Do | Caught by |
|-----------------------|----|-----------|
| Swallow errors (`catch (_) {}`, `on Object {}`) | Typed failures (`Result`, `AppFailure`); **log inside every catch** (what failed, with the cause); show a person one sentence | Machine: the architecture test's ratchet "no new catch-all that ignores the error" |
| Let screens or engines talk HTTP | HTTP only in `data/` and the composition root; screens read the local database and providers | Machine: architecture test |
| Make the screen wait for the network | The phone's database is the screen's single source; edits are local first and delivered later (outbox); `runApp` before any network | Convention; tests of the data layer |
| Wait on anything without a limit (E1: after the network came back the player spun for 50+ s and every tap did nothing) | Every slow or outside call has a **timeout** and a state the screen can show; the newest tap wins (12 s load limit, P1-08) | Convention; engine tests |
| Poll when you can listen (a 3-second probe; worst case 7.4 s) | The live channel pushes; a slow poll is only the safety net (60 s) (ADR-R27) | Convention |
| Skip silently when something is unavailable (E2: offline, the player hopped through 61 songs) | Say what is unavailable; grey the row; never auto-skip | Convention; offline tests |
| Write a file straight to its final name | Temporary file, check size or checksum, then rename (downloads, backups) | Convention; tests |
| Unformatted or lint-failing code; a Future nobody awaits; a subscription never cancelled; `print` | `dart format`, `dart analyze --fatal-infos` (warnings and infos fail). A stricter profile (`app/analysis_options_strict.yaml`: strict casts, inference and raw types; unawaited futures, uncancelled subscriptions, unclosed sinks and `print` are errors; sorted imports) applies to `lib/{app,core,data,design,domain,features,playback}` and the matching `test/` folders | Machine: pre-commit and the App workflow |

### D. The server (Python)

| Don't (what happened) | Do | Caught by |
|-----------------------|----|-----------|
| Start a program per request (B3: a new yt-dlp process each call, 0.6 s of start-up and no warm cache; B2: up to **8** programs for one song) | A warm worker; one look-up for one question; look-ups for the likely next tap happen ahead of time (`04` §4) | Convention; speed measured, not asserted (section E) |
| Repeat work, or let one person starve another | **Single flight**, reuse before work, strict priorities, fair share per person, one YouTube budget for the whole server (`04` §10, ADR-R6) | Machine: scheduler unit tests; convention for new work |
| Untyped, unlinted code | `ruff` (E, F, I, UP, B, SIM), `ruff format`, `mypy --strict`, `pytest` | Machine: the Server workflow |
| Shell scripts that run on other people's computers without a check | `shellcheck` and `bash -n` on the installer and the `encore` command | Machine: the Server workflow (`install-scripts`) |
| Change stored data without a way back | Numbered SQL files in `migrations/`; a backup before `encore update`; a restore that was **tried** on another machine (ADR-R37, `c02`) | Machine for the backup tests; convention for each new migration |
| Log or return a secret | `.env` mode 600, random keys, hashed invitation codes; never log a token, a password or a signed address | Convention (gitleaks only sees committed secrets) |

### E. Speed and measurement

| Don't (what happened) | Do | Caught by |
|-----------------------|----|-----------|
| Report the best case (B7: "tap to sound 3.6 s" held only when the page had been open for 10 s) | Measure what the person does (type, then tap at once); p50 **and** p95, or the worst of N; name device, network, server and line (`07` §2–3) | Convention: the PR template asks "Measured on" |
| Say "tests pass" and mean "it works" (A5: 1,430 green tests, and a ten-minute walk found 20+ problems) | Walk the screens as a person with the checklist (`07` §10) and attach the evidence | Convention; the reviewer re-runs the acceptance on a device or VM |
| Make the person wait for the slow part (B5: an import "about 2.3 hours left") | Make everything playable at once; do the slow work behind it (N4) | Convention |
| Guess where the time goes | Measure the stages (`perf` spans, server stage times); the 38 s turned out to be search, and 3 Mbit/s was a cap nobody had found (B4) | Machine for the budgets tagged `perf`; convention otherwise |

### F. Tests

| Don't (what happened) | Do | Caught by |
|-----------------------|----|-----------|
| Tests that would still pass if the feature were broken (A5: the same agent wrote the code and the tests that matched its assumptions) | Break the feature in your head: which test fails? A **reviewer who is not the author** re-runs the acceptance | Convention |
| Weaken a test to make it pass; skip one silently | Never weaken; a skip needs an issue number (`AGENTS.md`) | Convention |
| Journeys on fake data | Real data, made through the app like a user (`07` §8) | Convention |
| A walk written as prose, with no "expected" (`b01`, `b02`): a pass was a feeling | Fill **Expected** from the row **before** walking; write **Got** as the text on the screen or a number; the verdict follows (`07` §12). No row for what should happen? Write the row first | Convention; `tools/check_rows.py` lists the rows nobody tested (ADR-R41 T2) |
| A test named after a function, so nobody can tell which promise it keeps | Name it after the row it proves (`'DV-2: signing out ends the device of this phone on the server and deletes the saved sign-in'`) | `tools/check_rows.py` (report first, ratchet later) |
| Only the happy path, and "must not happen" untested (S2 survived 1,800 tests) | For every row that sends or stores something, a test that the **wrong** party gets nothing; a fault is produced on purpose (a proxy, a fake that answers badly), not only imagined | Convention; ADR-R41 T3/T4 |
| Screens that look right only on your phone | Golden pictures per operating system (ADR-R31); big text and tap targets are tested on the screens `accessibility_test.dart` covers | Machine on those screens; convention elsewhere |
| Bursts at YouTube from a test (the home address was refused on 2026-10-22) | **At most 10 look-ups per test run**, spaced; the server counts its look-ups per day | Convention; the counter shows it afterwards |

### G. What a person sees and touches

| Don't | Do | Caught by |
|-------|----|-----------|
| Jargon on a listener's screen ("Navidrome", "Subsonic", "codec", "port") | Plain words; technical words only on Host and Advanced screens | Convention (`07` §10) |
| Controls without a label, or clipped at big text, or under the navigation buttons | A semantics label on every control; works at font scale 2.0 and with 3-button navigation | Machine on covered screens (`labeledTapTargetGuideline`, `androidTapTargetGuideline`); convention elsewhere |
| A silent state (offline, refused, slow, empty) | Every state says what happened and what to do. A new, empty server says what to do next | Convention |

### H. Security and privacy

| Don't (what happened) | Do | Caught by |
|-----------------------|----|-----------|
| Commit passwords, logins, cookies, `.env`, keys, APK/AAB files (D1: six login files were pushed) | Login files live outside the repository (`local/logins/`) | Machine: the pre-commit hook, CI `forbidden-files`, gitleaks |
| Print, log, screenshot or paste a password | Type it with `python -I tools/journeys/ui.py typefile <login file>`, which types only the password line and prints nothing; never screenshot a visible password field | Convention |
| Let the Host see what a person plays | The Host sees who has an account and when they last signed in, never what they play (ADR-R33, `21`) | Convention; the privacy-matrix tests are planned (P3-09) |
| Risk a Host's internet address | Pace and back off; no bursts; no Google account; contain YouTube behind one interface (ADR-R2, `04` §5) | Convention |

### I. Repository and process

| Don't (what happened) | Do | Caught by |
|-----------------------|----|-----------|
| Work for weeks on one branch nobody pushes (D7: 46 commits stuck, CI never ran on the real work) | One task, one branch `task/<id>-<slug>`, a **draft PR on the first push**, push at least hourly, squash-merge (`06` §2) | Convention (branch protection is not on yet) |
| Trust a green check that did not run your change | Read which workflows ran: the App check runs only when `app/**` or `packages/**` change, the Server check when `server/**` does | Convention |
| Let documents sprawl (A1: 60 documents, nine plans) | `docs/` describes **the present**: one topic per file, about 300 lines at most, tables over prose; a document that disagrees with the code is a bug fixed in the same PR; decisions are ADRs with the options compared | Convention |
| Write a vague commit | `area: what changed for a person` | Convention |
| Hide what you did not test | The PR says what was not tested and why (the template has the heading) | Convention |
| Take the easy option that fixes it now and costs upgradeability, improvement or compatibility later: a placeholder file, a line commented out in a script, a symptom hidden in the screen, a hard-coded value, "leave it as it is" offered as an equal option (3 Nov 2026) | Find the root cause with proof, fix it at the source; a defensive layer is a second layer that stays correct afterwards; an unavoidable stop-gap says what it costs later and has a removal trigger, a task and a visible reminder; prefer a mechanism (a budget, a setting, a script that reverses only its own marked lines) to an edit in place | Convention |

### J. Installing and running it for other people

| Don't | Do | Caught by |
|-------|----|-----------|
| Ask a question after two minutes of installing (found on 2026-10-22: a missing password was noticed late) | Ask first, install after; every message says what to do next; never touch the person's music; an update makes a backup first (ADR-R19 to R26, R37) | Convention; the proofs `c01` to `c03` |
| Call a guide done because it works on your machine | Run it **as written** on a clean machine and write the time down; fix the guide where reality differs (`c01`) | Convention |
| Assume a dependency stays fresh (yt-dlp: the server only has the version of its last image build, and `encore update` brings it) | Know how each moving part gets updated; the permanent fix is P3-08 (`tasks/AUDIT.md`) | Convention |

---

## 2. If you see this in a diff, stop

* A `catch` with an empty body or an unused error; `on Object {}`.
* A `Future.delayed` or a `sleep` that "makes it work"; a retry loop with no limit.
* A new web address (`https://…`) in `app/lib` or a screen importing the HTTP client.
* A second copy of a function that already exists in another module.
* A number in a doc or a PR without the setup it was measured on.
* A test whose expected value was edited to make it pass; a skipped test with no issue number.
* A feature with no story, or a "TODO later" with no issue.
* A string built into SQL; a secret, a token or a signed address in a log line.
* A timeout of "none", or a state the screen has no words for.
* A fix that makes the happy path pass and leaves the failure path untested ("worked on my emulator").
* A decision of the kind "from now on we do X" that is written only in a chat or a commit message.
* A stop-gap (a placeholder, a commented-out line, a hard-coded value, a hidden symptom) with no removal trigger and no task for the proper fix.
* Two options offered where one is there only because it is easier and costs the future (upgradeability, improvement, compatibility).

## 3. Asking a stronger model, and when

Use the strongest model available to you: a reviewer or advisor tool if your environment has one, otherwise switch to the most capable model and give it the same material. It is
cheap next to a wrong architecture.

* **When:** before committing to an architecture or any hard-to-undo choice (section 0, question 8); before declaring a task of more than a few steps done; when stuck, when
  results do not fit what you expected, or when you consider changing approach.
* **How:** give it the question, the options, and the **facts you checked, with file and date**. Ask for a ranked recommendation. If your evidence disagrees with its advice,
  **say so and ask again**: do not silently switch to either. Its advice is an opinion; a measurement on a device is evidence.
* **Afterwards:** write the decision as an ADR (`11`): options, the choice, why it beats the others, and what was asked. Examples: ADR-R19 and ADR-R34 were decided this way.
* **Not for:** typos, formatting, anything a command answers in a minute.

## 4. Pull request self-review (paste into the PR; one line each)

1. What changed for a person, in plain words?
2. Which story and promise does it serve (`03a`, `03` §4)?
3. Does it add a call from a client to an outside service? (It must not: ADR-R38.)
4. What happens when it is slow, offline, refused, killed half-way, run twice, or run by two people?
5. Every number: measured on which device, network, server, line?
6. Which test would fail if the feature were broken? (Name it.)
7. Did I walk the screen as a person: plain words, labels, font scale 2.0, 3-button navigation?
8. Is any log line, test fixture or screenshot holding a secret, a login or a homelab detail?
9. Which workflows ran, and did the one for my change run?
10. What did I **not** test, and why?
11. Which docs describe the present and are now wrong? (Fix them in this PR.)
12. If this was a hard-to-undo choice: where is the ADR, and who did I ask?

## 5. Making a rule enforced: the ratchet

A rule written in a document decays. The cheap way to make it stay is a **ratchet**, as in `app/test/architecture_test.dart`:

1. A test scans the source text for the violation and counts it per file.
2. A **baseline** map lists today's known violations (so the gate is not red on day one).
3. A *new* violation fails the test. A baseline entry that has been *fixed* also fails, with a message to lower the number, so cleanup is always recorded.
4. The goal of every baseline is an **empty map**. A guard test checks that the scan really sees the code (a silent no-op is the failure to avoid).

**Built (the group `thin client` in `app/test/architecture_test.dart`):** the outside-host ratchet for ADR-R38. It counts, in `app/lib`, a literal `baseUrl: 'https://…'`, `Uri.http(s)(…)`, `Uri.parse('https://…')` and a request to a literal
address, with the baseline `deezer_client.dart: 1` and `lrclib_client.dart: 1`; an entry is lowered when P2-12 and P2-14 land. When the map is empty, the thin-client rule is
enforced by the machine for everything written into the source. It cannot see an address that arrives in data (a cover URL inside a record, `CoverFileService` fetches whatever it is given): that part stays a convention until the covers are served by the server.

## 6. Where to read more

`AGENTS.md` · `06` how a change travels · `07` how to test · `04` the architecture and §10 the rules against spaghetti · `28` the code module by module ·
`11` every decision with its alternatives (ADR-R38 is the thin-client rule) · `tasks/AUDIT.md` what is still open · `01` what went wrong and why.
