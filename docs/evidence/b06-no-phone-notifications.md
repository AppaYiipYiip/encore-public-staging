# B-06 — No phone notification unless the person asks, and the media controls still show (2026-10-24, ADR-R44)

Fourth walk in the record shape of `07` §12. Expected comes from `11` ADR-R44: nothing is posted to the phone by default; Android's notification permission is asked only when the person switches a category on; the media controls of a playing song are not affected (a media session is exempt on Android 13 and later: **to be verified with the permission denied**).

| Row | Setup | Steps | Expected | Got | Verdict | Evidence | If Fail |
|-----|-------|-------|----------|-----|---------|----------|---------|
| ADR-R44 (before) | The build of 2026-10-24 morning (`main`), Android 16 emulator | Sign in as a new person | (what it did) | "Allow Encore to send you notifications?" appeared **straight after the first sign-in** (seen in the walks of `b04` and `b05`), because the three alert switches were on by default | **Fail** | `b04` setup, the dialog dump | S3 → this change |
| ADR-R44 | **New build** (`task/notifications-off-by-default`, release x64). `pm clear`, then `pm revoke app.encore.player android.permission.POST_NOTIFICATIONS`. Emulator A, the dev server | Sign in with the form (address, name, password) | Home appears with **no permission dialog** | Home appeared; no dialog; `dumpsys package` shows `POST_NOTIFICATIONS: granted=false` | **Pass** | the run of this walk | — |
| ADR-R44, media controls | The same phone, the permission still denied | Open *The Dark Side of the Moon*, tap *Brain Damage* | The song plays and the media notification (lock screen and shade controls) still exists | Playing (`player_state`: PLAYING, audible); `dumpsys notification` lists the app's notification on the channel `app.encore.player.playback`, category `transport`, 3 actions, flags `FOREGROUND_SERVICE`, while the permission is `granted=false` | **Pass** | `dumpsys notification --noredact`, `dumpsys package` | — |
| ADR-R44, defaults | unit test | read the settings of a new install | the three alert switches are off | `alertsOnServer`, `alertsReleases`, `alertsImports` all `false` (and the background job reads the same defaults); switching one on still asks for the permission | **Pass** | `settings_wording_test.dart` (Notifications holds the three switches...), `alerts_service_test.dart` | — |

## What this does not do yet

* **The in-app bell does not exist in the app** (S-24 What's new is drawn, not built). With all phone alerts off by default, the new-release and "new on your server" alerts have **no place to appear** until the bell is built (P2-15). They are not lost: the person can switch them on in Settings > Notifications.
* Three switches remain on the page; ADR-R44 says at most two opt-in categories ("Jam invitations" first). The page is trimmed when the bell and Jam notifications exist.

## Setup in detail

| | |
|-|-|
| Phone | emulator A (`emulator-5556`, API 36, x64), release build of the branch, `pm clear`, permission revoked with `pm revoke` before the first start |
| Server | the dev VM's Encore server, person `newtester`; the password typed with `ui.py typefile` and TAB between fields (never printed) |

## YouTube look-ups spent

None (an album of the server's own library).
