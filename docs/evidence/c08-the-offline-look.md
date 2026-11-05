# c08: the lasting offline look and the "Can't reach your server." strip, on an emulator (5 November 2026)

**What this is.** A smoke test of P1-15 (R2-F5): after the strip has said "offline" once and gone, the screens keep showing what cannot be played (grey, "Not downloaded" in words, S-10/S-14/S-17/S-18), until the connection is back. **A smoke test on an emulator, not a walk.**

**Setup.** `app-debug.apk` (x64) from the branch `task/P1-15-offline-look` (on `main` `e796040`); emulator `encore_friend` (Android 16, API 36), signed in as `qaowner` to the test VM 108 (LAN). Airplane mode with `adb shell cmd connectivity airplane-mode enable|disable`; the screen read with `ui.py dump` (counts of "You're offline" / "Can't reach your server" / "Not downloaded") and pictures.

## Probe 1: airplane mode (CN-1), Home
| Time after airplane mode on | The strip ("You're offline...") | "Not downloaded" on Home |
|---|---|---|
| 5 s, 12 s, 19 s, 25 s, **34 s** (and a picture at 35 s: `c08-offline-home.png`) | not caught at 5 s (it appears after the 4 s grace and stays 5 s; the earlier R2-F5 run on the old build caught it at 4 to 8 s) | **9 on every sample, to the last one**: the tiles and shelves are grey and say "Not downloaded" (Liked Songs, ouch, P1 before backup, the albums) |

- The old build (R2-F5, same day): the strip appeared at about 4 s and was gone by 8 s, and **nothing** was left on Home or Library: this is what is fixed.
- **Library, Playlists tab**: every playlist row reads "..., Not downloaded", dimmed. **A playlist page** (`c08-offline-playlist.png`): its four songs are grey, "Not downloaded" where the artist stood, the cloud-off icon beside it (the existing dimming and icon stay).
- **Airplane mode off**: the look leaves by itself (0 on the next samples, Home and the playlist page).

## Probe 2: the server silent while the phone is online (CN-4b)
The VM was stopped (`qm stop 108`) while the emulator kept its network (two connected networks in `dumpsys connectivity`).
- The phone notices only when it asks something (nothing tells it a server went away: the resolver keeps its last answer): opening an album then showed the first song "not available offline" and Home showed the look (**9** "Not downloaded").
- A cold start of the app against the stopped server, polled every 2 s: at **11 s and 13 s the strip read "Can't reach your server."**, at 16 s it was gone (said once, 5 s); "You're offline" was **never** shown; **the grey look stayed on every sample to 40 s**, with the phone online.

## Probe 3: Android's own "does this network have internet" read (the words of the CN-4b strip, advisor's correction of 5 Nov)
The first words chosen for a silent server ("Can't reach your server." always) would have said again what the owner complained about on 31 Oct ("it never says offline"), for a 4G radio with no data. The strip now asks Android itself (`NET_CAPABILITY_VALIDATED`, one read through `app.encore/network`, 20 lines of Kotlin; no outside call): no internet found = "You're offline..."; internet found and a silent server = "Can't reach your server.".
- **Internet found, server stopped, cold start** (the new build): "Can't reach your server." at 10 s and 13 s, gone at 15 s, "You're offline" never; the look stays to 31 s.
- **Proof that the native read is wired**, not just compiled: the same probe with the Kotlin answer **temporarily forced to "no internet"** showed "You're offline." at 12 s and 14 s and never "Can't reach your server." (the forced line was removed again: the committed Kotlin is the real read).
- **Not reproduced:** a network that really has no internet (the emulator's validation could not be made to fail with `captive_portal_*` settings), a real 4G radio with no data, a sign-in page. The words for it are covered by `connection_banner_test.dart` with a fake read.
- **Known edge** (written in D-45): a Wi-Fi with no internet at all, with the server off, says "You're offline", as before this change.

## Not run, and why
Search offline (S-11, S-12: no offline state is drawn: it waits for its drawing); Home/Library on a wide screen or at 200 % text (the tests cover the cards at the sizes of the suite, not this probe); the first strip of Probe 1 was not caught on the emulator (the dump takes 2 to 3 s and the strip stays 5 s: its words and timing are covered by the widget tests `connection_banner_test.dart` and `offline_look_test.dart`); a real phone.

## Pictures
The only golden picture that changed is the "now playing, waiting for the server" one (the strip's words): the Windows one was redrawn here, the **Linux one by the Goldens (Linux) workflow** on this branch (run 41969982446, commit `35d099f`, looked at before the merge: the strip reads "Can't reach your server.", nothing else moved).
