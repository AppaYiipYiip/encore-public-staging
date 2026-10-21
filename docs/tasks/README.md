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

| Phase | File | State |
|-------|------|-------|
| P0 Reset | [P0-reset.md](P0-reset.md) | Ready (D-1 needed for P0-05 only) |
| P1 Instant play, worst bugs | [P1-instant-play-and-worst-bugs.md](P1-instant-play-and-worst-bugs.md) | Ready after P0-04 |
| P2 Songs as references | [P2-songs-as-references.md](P2-songs-as-references.md) | Ready after P1 (D-2, D-3 decided) |
| P3 One server, one-command install | [P3-one-server-and-install.md](P3-one-server-and-install.md) | After P2-01 |
| P4 Full feature set | [P4-full-feature-set.md](P4-full-feature-set.md) | After P3 (owner: everything in the first version) |
| P5 Public release | [P5-public-release.md](P5-public-release.md) | After P4; website and name not now |
| P6 Later | [P6-later.md](P6-later.md) | After the first public version |

## Before any task

* Work in the **new** repository once P0-04 is done; until then, P0 tasks work in `old-app/`.
* **Do not `git add -A` in `old-app/` before P0-01 is done**: login files with passwords are tracked there.
* The test servers: dev VM `encore-dev` (yours to change), CT 104 (read-only except test accounts). The owner's homelab: hands off.
* Test accounts' login files: `old-app/encore-*-login.txt` today, `..\local\logins\` after P0-01. Type passwords only with
  `evidence/scripts/typepw.py` (copy into `tools/journeys/`), never print them, never screenshot a visible password field.
