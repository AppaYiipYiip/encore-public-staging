# Tasks — how to use these files

One file per phase. Each task is self-contained: an implementing agent should be able to do it after reading **this file, the task,
the stories it cites (`../03a`), the architecture section it cites (`../04`), and `../06` + `../07` §1–3**.

## Task template (every task has these parts)

* **Why** — the findings it fixes (`../01` IDs) and the promise/story it serves.
* **Context** — facts the agent needs: files, measured numbers, gotchas, what was already tried.
* **Do** — the steps, in order.
* **Don't** — the traps.
* **Acceptance** — what a person sees, with numbers and the setup (`../07` §2) they are measured on.
* **Tests** — which levels (`../07` §6) and which journeys (`../07` §7).
* **Evidence in the PR** — what to attach.
* **Depends on / Size** — S ≤ 1 day, M 2–3 days, L 4–5 days (split anything bigger).

## Status board (planning agent keeps this current; GitHub Issues mirror it once P0-07 is done)

**Read first: [RELEASE-CANDIDATE.md](RELEASE-CANDIDATE.md)**, the plan before the owner is told a build is ready: what "pass" means now (walked as a real user on the published image and a same-commit APK, to the end state), the ordered blockers, the rehearsal's journeys, what a fresh test will still show, and every other open item. Update it, do not write a second list.


| Phase | File | State |
|-------|------|-------|
| P0 Reset | [P0-reset.md](P0-reset.md) | P0-01 to P0-08 done; P0-09, P0-10 and branch protection open |
| P1 Instant play, worst bugs | [P1-instant-play-and-worst-bugs.md](P1-instant-play-and-worst-bugs.md) | Core done; open items in [AUDIT.md](AUDIT.md) |
| P2 Songs as references | [P2-songs-as-references.md](P2-songs-as-references.md) | Server core and app data layer done; P2-03 to P2-18 partly, see [AUDIT.md](AUDIT.md); **P2-19 (find your server, ADR-R40): slice A merged (#11: a key as the server's identity, the server's own address list, the app half); slice B (the pairing code and QR) is parked unfinished, slices C (finding it on the Wi-Fi) and D are not started** |
| P3 One server, one-command install | [P3-one-server-and-install.md](P3-one-server-and-install.md) | P3-05 slice, backups and resumable install done and proved; P3-12 gates open; the rest open |
| P4 Full feature set | [P4-full-feature-set.md](P4-full-feature-set.md) | Not started (owner: everything in the first version) |
| P5 Public release | [P5-public-release.md](P5-public-release.md) | After P4; website and name not now |
| P6 Later | [P6-later.md](P6-later.md) | After the first public version |

## Before any task

* Work in the repository `encore/`.
* The test servers: dev VM `encore-dev` (yours to change), CT 104 (read-only except test accounts). The owner's homelab: hands off.
* Test accounts' login files: `..\local\logins\`. Type passwords only with
  `python -I tools/journeys/ui.py typefile PATH` (types only the `password:` line of a login file), never print them, never screenshot a visible password field.
