# B-10 — F21: Download on a catalogue release, on the build of PR #43 (2026-10-30)

AUDIT F21 reproduced on `main` in `b08` (green "In your library" at once, no progress, nothing saved on the server). This walk repeats it on the build of PR #43 (the app half of D-21, server half `#40` merged). Record shape of `07` §12.

## Setup

| | |
|--|--|
| App | An x64 **release** APK built from `task/F21-app-release-save` at `f900d7c` (`main` at `c8a1853` plus the F21 app change, pubspec `+122`); fresh install, notifications revoked, signed in with the form (the password with `typefile`, no dump after it) |
| Server | The dev server, running `main` at `c8a1853`: the 48 Python files of the package equal by hash. The access log was switched on in the dev copy for part of the walk and put back (the log was read with every credential masked) |
| Phone | Android emulator, API 36, x64, headless with software rendering |
| Release | *Our Time Is Now*, Gojira, 2022, **one song, one artist**, nothing of it on the server before |
| YouTube look-ups | One for this walk (the server's keep job); at most 6 for the whole day's walks. Nothing from the owner's server |

## Rows

| Row | Steps | Expected | Got | Verdict | Evidence |
|-----|-------|----------|-----|---------|----------|
| The screen after the tap | tap the download arrow on the release page | a ring while the songs arrive; the chip and the row check appear only once the server confirmed | **3 s after the tap:** the arrow is a **progress ring** (label "Downloading Our Time Is Now, 0 percent"), the chip says "In your library" and the row has its check (the server had answered: the next row), and a notice "Downloading Our Time Is Now for offline listening" | **Pass** | `b10-dl-2s.png` |
| What the server holds | read the account's library feed, then the server's database (read-only) | the save recorded; the song asked for and kept | **`savedAlbums: 1`** (`cat:365428397`, not removed) where `b08` had 0; a `work_item` of kind `keep` for the song, **state `done`, 1 attempt, created in the same millisecond as the save**; a `song_file` row (`Encore/Gojira/Our Time Is Now/01 - Our Time Is Now.opus`); the file appeared about **10 s** after the tap | **Pass** | the queries' output |
| What the phone holds | open Settings > Downloads & storage (after a restart of the emulator) | the song is on the phone | **"1 song downloaded, 4.0 MB"**, *Our Time Is Now, Song, High* listed with its remove button | **Pass** | `b10-downloads-storage.png` |

**F21 is fixed on this build for one ordinary release of one song.** The chain is the one D-21 asks for: the tap makes the server save the release and keep its song; the song reaches the phone; the phone downloads it.

## Not shown (said plainly)

* The ring and the chip were read **once, 3 s after the tap**. The states at 30 s and 120 s were not recorded: the emulator and the dev machine were shut down while the song downloaded, and the phone held it when they came back.
* A release of **several songs** (the ring's progress, "some songs failed", the manager waiting while the server fetches them one by one at its own pace), a server that does not answer, a song YouTube refuses, and **Add to library on its own** were covered by unit tests (`PB-33` to `PB-37`) but **not walked**. The Library > Downloaded tab and the release page after a restart were not looked at.
* The phone lists the download as a **song**, not as the album (a pin per song). Whether that is what a person expects is not decided.
* **F29** (the first download asks for notification permission) is **not fixed** in this build; the dialog was not seen in this walk (it may have appeared after the first screenshot and gone unanswered while the emulator was off).

## Found on the way: F30, the first two minutes

On a fresh sign-in the app **stays in the old music-server mode for about two minutes**, then switches to Encore mode by itself. Server log, in order (the dev machine's clock runs 45 s ahead of this PC's):

| Start | What the server saw from the phone | After |
|-------|------------------------------------|-------|
| a cold start at 14:41:52 | an identity probe, two looks at `/info`, then the upgrade (`POST migrate/navidrome`, device login, cover pass, library feed) at 14:44:42 | **2 min 50 s** |
| a fresh sign-in at 14:46:24 (PC clock; 14:47:09 on the server's) | the upgrade call at 14:49:08 | **1 min 59 s** |

Until then the phone works as against a plain music server: the page says "It is added to your library first, which takes a few seconds" (the old wording), and **Add to library and Download run the old code path**. A person who installs the app and taps at once, as the owner did, gets that path. The cause is not found: the first look at `/info` after the address check does not lead to the upgrade and the next one, after the retry pause, does (`ServerSession._detectAndUpgrade`, which waits 2 minutes, doubling). Recorded as AUDIT F30.
