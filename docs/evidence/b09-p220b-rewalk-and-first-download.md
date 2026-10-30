# B-09 — PR #33 (P2-20 slice 2) walked on the branch brought up to date with `main` (2026-10-30)

PR #33 (songs and pictures by the server's signed address, no music-server login on them) predated several merged pull requests. It was merged with `main` at `cdadac1` (a clean merge, branch tip `4720792`) and re-walked before the F21 app half, which changes the same download path. Record shape of `07` §12.

## Setup

| | |
|--|--|
| App | An x64 **release** APK built from the branch tip `4720792` (#33 plus `main`), `pm clear`, notifications revoked, signed in with the form (the password with `typefile`, no dump after it) |
| Server | The dev server, running `main`'s files (equal by hash, `b08`); #33 needs nothing newer on the server |
| Phone | Android emulator, API 36, x64, headless with software rendering (timings are comparable with `b08`, not with `b07`) |
| YouTube look-ups | None (kept songs only) |
| Not covered | A real phone, an arm64 build, the away-from-home address, a signed address that runs out during a song (6 h), a download of a song that is not kept yet (that is F21), the impostor server (`b03`) |

## Rows

| Row | Steps | Expected | Got | Verdict | Evidence |
|-----|-------|----------|-----|---------|----------|
| Pictures | sign in, look at Home | covers drawn, not letters | the three album covers drawn (Dark Side, the way of all flesh, QUE CE SOIT CLAIR) | **Pass** | the screen |
| N1, a kept song | tap four rows of *The Dark Side of the Moon*, twice round | 3 s hard limit, 0.7 s target | **n = 8, median 1.19 s, min 0.94, max 1.66** (`b08` on `main`, same emulator: median 1.45 s) | **Pass**: not slower | the script's output |
| Download of kept songs (the case `b07` did not walk) | open the album, tap the download arrow, then Settings > Downloads & storage | the album ends on the phone | "Downloaded. Tap to remove *The Dark Side of the Moon* from this phone"; **10 songs downloaded, 42.3 MB**, the album listed with its quality | **Pass** | `b09-downloaded-album-on-the-phone.png` |
| A downloaded song, the server away | stop the server, tap a downloaded song | plays; no "Waiting for your server."; no error | the title stayed, no sentence, no error notice, sound present when the server came back (0.6 s) | **Pass** | the script's output |
| **First download and the notification permission** | the same first tap on the download arrow | **no** notification dialog (ADR-R44: nothing is asked or posted unless the person switches it on) | Android's **"Allow Encore to send you notifications?"** covered the page until answered; after "Don't allow" the download carried on and finished | **Fail** (against ADR-R44) | `b09-first-download-asks-for-notifications.png` |

## Why the permission is asked (read in the code)

`BackgroundDownloaderTransport._ensureNotificationPermission` (`data/downloads/background_downloader_transport.dart`) asks "once, in context (the user just pinned something)" and configures running, complete and error notifications for the download group. #29 (ADR-R44) switched off the three alert switches and the request at sign-in; it did not touch this one. Downloads work without the permission (the walk declined it). Seen on this build, which carries `main`'s #29; not tested on `main` alone. Recorded as AUDIT F29.

## Correction (written later the same day)

* **The Server row above is wrong about #33.** The dev container ran `main` at `346bd75`, which **lacked #33's own server half** (the cover pass, `GET covers/pass`, and the length hint for quality extras; both arrived with #33). "#33 needs nothing newer on the server" was false. The "Pictures" row therefore exercised the fallback path, not the one-ticket path #33 introduced.
* **The phone may have been in the old mode.** The first two minutes after a sign-in run the old music-server code path (AUDIT F30, `b10`), and this walk did not look at the page's wording. That the album downloaded is therefore not shown to be the Encore path.
* Checked again against the complete server in `b10`: the cover pass answers (401 without a login, so the route exists), the phone asked for it twice at its upgrade, and Home drew its covers.
