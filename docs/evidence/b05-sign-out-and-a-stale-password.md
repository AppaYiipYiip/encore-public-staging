# B-05 — Signing out ends the phone's device on the server; a phone with an old password locked the account (2026-10-24, D-5)

Third walk in the record shape of `07` §12. Rows: `32` DV-2 (revoked: sign out), `31` CN-24 (the login is refused), `32` AC-21 (an account is locked after twenty wrong tries) and DV-4 (a lock ends all the person's devices).

| Row | Setup | Steps | Expected | Got | Verdict | Evidence | If Fail |
|-----|-------|-------|----------|-----|---------|----------|---------|
| DV-2 (before) | `main` at `efd41d8` (by reading the code and the walk list of 2026-10-23) | the person signs out | the device is revoked on the server | the app never called `POST /auth/logout`; the dev account (`newtester`) showed **four active devices** after several sign-outs and `pm clear`s, two of them `Android phone` entries of phones that no longer existed | **Fail** | `devices_of.py` output of 06:12 | S3 → D-5 |
| DV-2 (server) | the server tests | `POST /auth/logout` with the music server's login (the way the app asks) and another person's device id in `X-Encore-Device` | only the caller's own device is ended | **Fail** before the change: the id in the header was revoked whoever owned it (the endpoint only checked the id's shape, unlike `DELETE /me/devices/{id}`) | **Fail**, fixed | `test_dv_2_signing_out_never_ends_somebody_elses_device` (fails without the fix, `api.py` `logout` now has `AND person = ?`) | S3 (needs the other person's device id, 26 random characters) |
| DV-2 | **New build.** Emulator A signed in as `newtester` at `192.168.50.133:4540`; the server lists 1 active device (`Android phone`) | Home, Settings, scroll to the bottom, Sign out, confirm | The phone shows the first screen; the server lists **0** active devices for the account; nothing else of the person is touched | The first screen ("Welcome to Encore") appeared; **`GET /me/devices` went from 1 to 0**, the database row of that device has `revoked_at` set; the failed-login counter stayed 0 | **Pass** | `tools/journeys/devices_of.py` before and after (above), the device table | — |
| DV-2 (offline) | unit test | sign out with the server unreachable | the phone still signs out; the device stays valid on the server until ended from another device (DV-3) | passes: the saved sign-in is deleted, the call is given 5 s and its failure ignored | **Pass** (unit test; not walked on a phone) | `DV-2: signing out with no connection still forgets the sign-in, and says the server was not told` | — |
| CN-24 / AC-21 (found by accident) | The second emulator (B) had been signed in as the same person since journey 4 (`b02`), with the **old password**; the test password was rotated about five hours earlier (a leaked password, `b04` F-3), which signed B's device out | nothing: B's live channel tried to renew its device sign-in | A refused password shows the "Sign in again" card and stops (`31` CN-24) | **B tried the old password again and again** (its live channel renewed the device sign-in with the stored password at every reconnect, 1 to 30 s apart): `failed_logins` reached 20 over the following five hours and the server **locked the account**; after the unlock the counter went 1, 3, 8 in under three minutes while B was awake (`This account is locked.`, DV-4: all its devices revoked). Nobody noticed on B (its screens showed "Synced 4 h ago") | **Fail** | the account row, `devices_of.py` ("the server said: This account is locked."), the device table | S2 (a stale phone locks the owner out of their own account) → the fix below |

## The fix to the stale-password lock (same pull request)

* `EncoreDevice.token()`: a password the server **refused** is not sent again for 15 minutes (four tries an hour, far from the twenty that lock), then tried once more in case the server was only busy. A new sign-in makes a new object with the new password.
* `EncoreApi.login` returned an `UnexpectedFailure` for a 401 (it did not go through the server's error mapping): a refused password is now an `AuthFailure`, which is what the phone's other code already expects (`31` CN-24).
* Test `CN-24: a password the server refused is not tried again for a while (twenty wrong tries lock the account)`: six calls over five minutes make one login.
* Not walked on a phone after the fix (it needs a phone that holds a wrong password again): the unit test and the incident are the evidence. **Open:** nothing tells the person on B that its login was refused (the "Sign in again" card is for the music-server login that sync uses; the live channel's refusal is silent). Written down for P1-12/P2-18.

## Setup in detail

| | |
|-|-|
| Phones | emulator A (`emulator-5556`, build 120 of the branch, signed in again after `pm clear`), emulator B (`emulator-5558`, an older build, signed in as the same person; signed out by hand during the walk through its own Sign out, which ended its device on the server only if it had a valid one, and it did not) |
| Server | the dev VM's Encore server (slice A), people `newtester` (owner), `friendone`, `walkerthree` |
| Measuring | `tools/journeys/devices_of.py` (asks `GET /me/devices` with the token login, so it adds no device; prints ids, names, last seen, never a secret); the dev database read inside the server container for `revoked_at` and `failed_logins` |
| Songs | none played |

## Findings that are not rows

* **F-1: a phone signed in with an old password is invisible to its owner.** B showed a normal Home for hours. The sign-in card of CN-24 comes from the music-server login that sync uses; B's sync evidently kept working through the music server's own check or was quiet, so nothing said "sign in again". To investigate with the open item above.
* **F-2: the same password reached a screen dump** (`b04`, F-3): rotated at once; this is why the account was rotated and why B's old password was wrong in the first place. A password rotation therefore **must also sign out or re-sign-in every phone that holds the account** (a checklist line in `local/credentials-map.md`).
* **F-3: `ui.py` taps by coordinates went wrong twice** (the dialog's Sign out button is at different y on the two emulators): always take the coordinates from a fresh dump of that phone.

## Not covered

Sign out while a song is playing from the server (the playback is stopped first; not timed); sign out on a plain (non-Encore) server (no device exists; the step does nothing); the person's device list screen in the app (does not exist, DV-3/DV-5); a phone that is signed out while the server restarts.

## YouTube look-ups spent

None.
