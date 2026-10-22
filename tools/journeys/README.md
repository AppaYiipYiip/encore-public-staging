# tool/journeys - driving the emulator like a person (docs/12 section 5)

Small standard-library scripts used to run the journeys against the real server. None contains a secret: logins are read from a
**login file** (`address:`, `user:`, `password:` lines, kept outside the repository) passed as an argument, and are never printed.
Run with `python -I`. The device defaults to `emulator-5556` (`ANDROID_SERIAL` overrides it); adb is `C:\dev\android-sdk\platform-tools\adb.exe`.

| Script | What it does |
|--------|--------------|
| `ui.py` | `dump` lists what is on screen with positions; `tap "text"`, `tapxy`, `swipe`, `type`, `typefile` (a password from a file, pushed, typed and deleted), `key`, `shot NAME`, `wait`/`gone`. **Never tap blind**: run `dump` first. The sign-in fields have empty labels, so use their positions from a dump; never take a screenshot while the form is filled in |
| `nd.py LOGIN METHOD [k=v ...]` | One Subsonic call as that person, shortened output (the server's own view, for checking that a like or a playlist really arrived) |
| `sync_timing.py LOGIN "Playlist name" [runs]` | R-16: a "second device" adds a song through the API, how long until the phone's Library list shows the new count (random gaps, p95) |
| `people_rehearsal.py` | Starts the people service and a loopback "front door" (`/people` to the service, the rest to the real music server) so the emulator can use friend activity and invitations before the real Funnel exists: add `http://10.0.2.2:8712` as an address in the app. Reads the administrator login from the login file, prints nothing secret |
| `two_phone_timing.py A B X Y TEXT [S]` | Journey 4: taps one point on phone A (the last step of an action) and says how long until TEXT shows on phone B's screen (an upper bound: one screen dump costs about a second). Both phones on the screens where the change will show |
| `people_call.py LOGIN METHOD PATH [JSON] [--base=URL]` | One call to the people service as that person (what the app sees: `/people/api/me`, `/people/api/activity`, `/people/api/invites`) |

Notes: `uiautomator dump` sometimes fails while the lyrics animate or a toast shows ("could not read the screen"): take a screenshot instead. The
dump delivers a bullet character as a replacement character; match with `\W`.
