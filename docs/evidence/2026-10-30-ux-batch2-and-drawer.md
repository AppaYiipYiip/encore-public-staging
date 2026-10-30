# UX review batch 2, and the drawer walked on an emulator (2026-10-30, night)

**What this is.** The rest of the screens the batch 1 record listed as "not looked at", and a walk of the avatar's drawer (PR #60, merged as
`1a30765`). **A review and a walk on an emulator against the dev VM, not the release-candidate pair: it is not a pass**
(`docs/tasks/RELEASE-CANDIDATE.md` section 1). The build was an x64 release APK `0.1.0 (build 122 · ba47e27)` (the head of #60). The dev VM runs the old
stack beside the new server. Pictures: `evidence/2026-10-30-ux2-*.png`.

## Batch 2: screens looked at

| Screen | Frame | What the build shows | Verdict |
|---|---|---|---|
| Settings > Playback | S-72 | Streaming quality (Wi-Fi: Original, mobile: High), Equalizer, Volume levelling (Off / Song / Album), Quiet places | Readable, no defect for RC1 |
| Settings > Library & sync | S-72 | Songs on this device, last sync, sync while closed, Sync now, Rebuild library | **F54** the last sync is a raw timestamp (`2026-10-30 19:43:04`) |
| Settings > Notifications | S-72 | Three switches, all off, one honest paragraph | Readable. The release check sends artist names to the public catalogue from the phone (known thin-client debt, ADR-R38) |
| Settings > Lyrics | S-72 | Text size, keep screen on | Fine |
| Album page (`ux2-album`) | S-18 | Cover, title, artist, year, N songs, minutes, Download, menu, shuffle, play, numbered rows with their own menus | Matches the frame's intent, no defect |
| Library > Artists, Artist page (`ux2-artist`) | S-19 | Hero, "1 of 15 albums on your server", Popular, Albums | Honest about what the server holds. No defect |
| Queue sheet (`ux2-queue`) | S-33 | Now playing, "Nothing queued" with how to add | **F55** a lone "Save" on the sheet does not say what it saves |
| `/profiles` with one person (`ux2-profiles-one`) | S-05 | "Who's listening?", the person, "Add someone" | The page behind Settings > Switch user; the avatar no longer opens it (D-34) |

## The drawer (S-27, D-34), walked

| Step | Expected | Got | Verdict |
|---|---|---|---|
| Tap the avatar on Home (one person) | A drawer from the left: name, then only rows that exist | `newtester`; What's new (this server keeps news), Settings, Your server "My music server · Connected", Add account, Sign out. No Jam (no hub), no People (not an owner) | As designed |
| Tap What's new / Settings / Your server | The place opens, the drawer closes, Back returns to Home | All three, each time | As designed |
| Tap Sign out, then Cancel | The same question as Settings ("Sign out of My music server?"); Cancel leaves the drawer open | Yes | As designed |
| Add account (second test person), then the drawer | A "Who's listening" block with both, a check on the active one, "Add someone" instead of "Add account" | Yes (`ux2-drawer-two-accounts`) | As designed |
| Tap the other person in the block | One tap switches; Home and the queue are theirs | Yes | As designed |
| **Sign out from the drawer, as the second person** (advisor's check) | The question, then "Who's listening?" with only the first person, nothing thrown | Yes: landed on "Who's listening?" with `newtester` "Listening now"; no crash and no disposed-reference error in logcat | As designed. The drawer's `ref` lives through `signOut` |

Also seen on the real build: **Home has no Jam chip** (F50 working), and the drawer's Jam row is absent for the same reason.

## Not done

A drawer with the People and Jam rows on a real server (no owner login or Jam hub on this VM; the widget tests cover them); the drawer on a fresh install
(the accounts list is now started at the app root: `b11`); anything on a real phone.
