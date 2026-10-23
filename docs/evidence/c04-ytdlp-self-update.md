# c04 — The server updates its own yt-dlp (P3-08b, ADR-R39), run for real

Date 2026-10-23. Code: branch `task/P3-08b-ytdlp-updater` (PR #9). Everything below was seen, not assumed; what was not seen is in the last section.

## Setup

| | |
|-|-|
| Machine | the dev VM `encore-dev` (Docker; the owner's home line, the address YouTube sees is the home address) |
| Server | the branch's server image built on the VM, run as a throwaway container (own port, own data folder, no music server behind it), `restart: unless-stopped`, `ENCORE_AUTO_TOOLS=1` |
| Starting point | an image with **yt-dlp 2026.8.19** baked in on purpose, so that PyPI's **2026.10.21** (released 2026-10-21, newest on 2026-10-23) counts as newer |
| What drove it | nothing but the server's own updater thread (first check 5 to 30 minutes after start, by design) |
| YouTube look-ups | **4 check runs between 20:38 and 21:01 (23 minutes)**, none refused (rule: at most 10 per test run). A run can make two attempts inside (the fast client, then the fallback); the server counts a run as one look-up |

## What happened, in order (UTC)

| Time | Event |
|------|-------|
| 20:30:32 | Container 1 started. `/info`: `tools.ytDlp = {running: 2026.8.19, pending: null, state: ok}` |
| 20:38:18 | The updater's first check (7.7 min after start). It found 2026.10.21, downloaded it and ran the check, which answered "the fixed video is not available": **no change made** (look-up 1) |
| 20:38:46 | By hand, the same child on the old copy: `ERROR: [youtube] jNQXAC9IAdQ: This video is unavailable` (look-up 2). The first choice of check video, YouTube's first upload, does not play on the path songs take |
| 20:39:12 | By hand, the newest yt-dlp on Blender's "Big Buck Bunny" (`aqz-KE-bpKQ`) through the same path: `{"ok": true, "version": "2026.10.21", "bytes": 65536}` (look-up 3) |
| 20:41:40 | Container 2 (check video changed, fresh data). `running: 2026.8.19` |
| **21:01:15** | The updater's check (19.6 min after start): `yt-dlp 2026.10.21 is ready and passed the check on the path that plays songs; the server switches to it at its next start, which waits for a quiet moment (now running 2026.8.19)` (look-up 4). Stored wheel 3,188,012 bytes, sha256 `94a3a3e2…c247` = PyPI's |
| **21:02:16** | `nothing has gone through the server for 60 s: restarting to switch to yt-dlp 2026.10.21`; clean shutdown |
| **21:02:17** | `yt-dlp: running the stored copy 2026.10.21 (the image carries 2026.8.19)`. Docker `RestartCount 1`; 1.3 s from the restart decision to the new process's first log line. `/info`: `running: 2026.10.21, pending: null` |

## Failure drills (no YouTube traffic)

| Drill | Result |
|-------|--------|
| The stored wheel cut short (an interrupted write), then restart | One warning (`its file does not match the stored checksum; using the image's own copy`), server up, `running: 2026.8.19` |
| The stored wheel deleted (a copied folder), then restart | One warning (`its file is missing or unreadable … using the image's own copy`), server up |
| The wheel put back, then restart | `running the stored copy 2026.10.21` again |

## Two real defects this run found, both fixed in the PR

1. **The check video.** "Me at the zoo" is not playable on the song path ("This video is unavailable"). Changed to "Big Buck Bunny" (an open film on the Blender Foundation's channel); the updater now also logs why a check did not pass.
2. **A restart loop.** After either drill above, `/info` still said `pending: 2026.10.21`, because the pointer still named a newer version than the one running. The restarter would have restarted the server every quiet minute for ever. Fixed twice over: an unusable pointer is removed at start (the next daily check fetches the release again), and the server restarts at most once for any one version. **Re-run after the fix:** wheel cut short, restart → pointer removed, `pending: null`; 150 s later still no restart (no `restarting` line in the log).

Both were invisible to 560 unit and integration tests, which is why the real run was done last.

## After the run

* **The playlist reader's child** (the one place that used to start a `yt-dlp` command): `python -m yt_dlp --version` printed `2026.08.19` in the image and `2026.10.21` with the stored wheel on `PYTHONPATH`; and after the server's own `activate()` the very child it starts printed `2026.10.21` (image 2026.8.19). No YouTube traffic.
* **Removed:** the throwaway container, both test images and the test folders were deleted from the dev VM (`docker ps -a` showed only the services that were there before), so it cannot be a second YouTube client on the home address.

## Not seen (and why)

* A restart **with phones holding the live connection** (the live channel does not count as activity; uvicorn closes it on shutdown and the hard exit after 30 s bounds it; phones reconnecting after a server restart was seen in `b01`, not after this restart).
* A server that is **never quiet** was only tested with a fake clock and a fake "busy"; no real stream was held open during a pending update.
* A **download whose checksum is wrong** was only tested against a mocked PyPI.
* The **second and later days**: one check per container life was seen, not the 24-hour rhythm, the 4-run daily budget or the hourly retry after a failure.
* **`degraded`** (the running copy failing the check too) and **a candidate that fails while the running copy passes** were only run with fakes: the real YouTube never failed the check on a working copy.
* **arm64**, a **slow line**, VM 107 (the owner's: untouched) and **the real music server behind it** (the throwaway container had none).
* That the stored copy is the one **imported** by the server process was shown by the log line after `sys.path` is changed, the unit test with a fresh interpreter (`test_the_stored_copy_really_wins_over_the_installed_one_in_a_fresh_interpreter`) and `/info`, not by asking the running process which file it loaded.
* A **removed check video** makes the updater say "cannot check" and do nothing (unit tested); it would then need a new image with another video.
