# B-01 — The live channel: one person, two phones (2026-10-22, build 113)

**Setup.** Two Android emulators (720x1600, host GPU), both signed in as the same person on the dev VM server
(`http://192.168.50.133:4540`, home network). Phone A made the change; phone B was left on the screen where it would show (Your
Library). `tools/journeys/two_phone_timing.py` taps the last step on A and polls B's screen until the text shows. One screen dump
costs about a second, so every time below is an upper bound.

**How it works.** The app signs in once as a *device* (a token kept in the phone's secure storage, reused until the server refuses it),
opens `/encore/live`, and the server pushes `library.changed` to the person's other devices. The app then asks for the changes at once.
While the connection is up the periodic check is a 60 s safety net; when it drops the 3 s check returns and the app reconnects with a
jittered pause (1, 2, 4 ... 30 s). The connection is closed when the app goes to the background.

| Change on A | Shows on B after | Note |
|-------------|------------------|------|
| New playlist "Sync test one" | 2.5 s | first trial |
| New playlist "Sync test two" | 2.5 s | |
| New playlist "Sync test three" | 2.5 s | |
| New playlist "Sync test four" | 2.5 s | |
| Like a song (Liked Songs 4 -> 5 on B) | 2.4 s | unliked afterwards |
| New playlist "Sync test five" | 2.6 s | **after the server container was restarted**: both phones had reconnected within 45 s without any tap |

Before the live channel (the old project's docs/23, B40: not in this repository): checks every 3 s, worst case 7.4 s against the 5 s budget (R-16). The server log shows two
`WebSocket /encore/live [accepted]` lines after the restart (one per phone), and the person has two devices on the server (one per phone, not
one per app start).

**Not covered here.** An import and a resume on one phone appearing on the other; the same over the public address; a phone coming back
from hours in the background; more than two phones.

**Found on the way.** Right after a phone booted, the first open of an invitation said "Can't reach ..." once (no network yet); the app
does not retry by itself (a task for the join screen).
