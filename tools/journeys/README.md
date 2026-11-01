# tools/journeys - driving the emulator like a person (docs/07 sections 3 and 12)

Small standard-library scripts used to run the journeys against the real server. None contains a secret: logins are read from a
**login file** (`address:`, `user:`, `password:` lines, kept outside the repository) passed as an argument, and are never printed.
Run with `python -I`. The device defaults to `emulator-5556` (`ANDROID_SERIAL` overrides it); adb is the one in `ui.py` (`ADB`, a path on the owner's PC: change it on another machine). Every script of this folder is listed below.

| Script | What it does |
|--------|--------------|
| `ui.py` | `dump` lists what is on screen with positions; `tap "text"`, `tapxy`, `swipe`, `type`, `typefile` (a password from a file, pushed, typed and deleted), `key`, `shot NAME`, `wait`/`gone`. **Never tap blind**: run `dump` first. The sign-in fields have empty labels, so use their positions from a dump; never take a screenshot while the form is filled in |
| `nd.py LOGIN METHOD [k=v ...]` | One Subsonic call as that person, shortened output (the server's own view, for checking that a like or a playlist really arrived) |
| `sync_timing.py LOGIN "Playlist name" [runs]` | R-16: a "second device" adds a song through the API, how long until the phone's Library list shows the new count (random gaps, p95) |
| `people_rehearsal.py` | Starts the people service and a loopback "front door" (`/people` to the service, the rest to the real music server) so the emulator can use friend activity and invitations before the real Funnel exists: add `http://10.0.2.2:8712` as an address in the app. Reads the administrator login from the login file, prints nothing secret |
| `two_phone_timing.py A B X Y TEXT [S]` | Journey 4: taps one point on phone A (the last step of an action) and says how long until TEXT shows on phone B's screen (an upper bound: one screen dump costs about a second). Both phones on the screens where the change will show |
| `cold_start_timing.py RUNS` | N1 from a cold start: stops the app, starts it, opens Liked Songs once Home is drawn, taps a streamed song and times the seconds from the tap to sound |
| `devices_of.py LOGIN` | The devices an Encore account has signed in on (id, name, last seen; never a secret), for a walk that must show a device appear or go |
| `fault_walk.py pb-f7 ...` | Faults on purpose (ADR-R41 T4): a Toxiproxy between the emulator and the dev server takes the server away and back while a song is asked for or playing; prints a timeline and the numbers a walk record needs |
| `fetch_call.py`, `fetch_timing.py`, `stream_call.py`, `import_call.py`, `hub_call.py` (each: `LOGIN` first) | One call to the old services as that person (the password is never printed): the fetch service, the "play any song" timing (J-04), a streamed song's first byte, the imports, the Jam hub. The Encore server's own API is `nd.py` and `devices_of.py` |
| `impostor_server.py` | A server that is not your server (`evidence/b03`): answers at an address with the real server's id and public key, cannot sign, and writes down only the names of what a phone sends it |
| `perf_session.py LABEL [scenario ...]` | What a person feels: frames while scrolling, memory, cold start |
| `play_timing.py` | What a person waits for: search for a song, tap it, time until sound is really coming out (`07` section 3) |
| `history_probe_test.dart`, `lyrics_probe_test.dart` | Two Dart probes run by hand with `flutter test` against the real server or LRCLIB; not part of the suite |
| `people_call.py LOGIN METHOD PATH [JSON] [--base=URL]` | One call to the people service as that person (what the app sees: `/people/api/me`, `/people/api/activity`, `/people/api/invites`) |

Notes: `uiautomator dump` sometimes fails while the lyrics animate or a toast shows ("could not read the screen"): take a screenshot instead. The
dump delivers a bullet character as a replacement character; match with `\W`.
