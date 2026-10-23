# C-03 — An install that is cut short, and the music server's sign-in limit (2026-10-23)

Found by the final proof from `main` (cut off at the test driver's 15-minute limit while the second image was still downloading) and fixed on
`task/P3-12-install-resume`. Machine: VM 107, Ubuntu 26.04, installed by the guide's steps from the branch image.

| Check | Result |
|-------|--------|
| **The terminal is closed in the middle** of the install (the connection is cut when "Downloading the music server" starts) | the installer carried on without it: images downloaded, Encore started, the owner's account made, the nightly backup switched on and a first backup taken, `=== done after 960 s` in the log; the owner signs in; no marker left |
| A finished install | `encore status` has no "cut short" line |
| The marker is there and the account exists **with the same password** (a cut just before the marker was removed) | the installer says it is finishing an earlier install, asks only for the owner's details (given by the options here), reports the account, removes the marker |
| The marker is there and a **different password** is typed | refused in a sentence ("made by an install that was interrupted, with a different password. Type the password you chose the first time, or run `encore uninstall --everything`"); the marker stays; nothing changed (before this fix the second password was silently ignored and the person would have believed it) |
| `encore status` while the marker is there | says the first install was cut short and to run the installer again |
| The account was **never made** (deleted through the music server's own API to look like a run cut off before it), marker present, a **new** password | the installer finishes the setup: the account is made with the new password, the marker is removed, `encore status` is clean, the new password signs in (10 s, images already there) |
| The resume run **three times back to back** (each signs in to the music server several times: this is what met the 429s) | all three report the account; no refusal (with the fix below) |
| A password file that does not exist | "The password file X cannot be read." instead of "Something went wrong at line 67" |

## The music server's sign-in limit

Running the installer again straight away asks the music server to sign in four or five times in a few seconds; it answers HTTP 429 (five sign-ins in
twenty seconds, counted for the whole computer) and the Encore server took that for "this server's own account was refused". Found by the run that
deleted the owner and ran the installer a third time within a minute. Now every sign-in the Encore server makes waits the few seconds the music server
asks for and tries again (three more times); if it still refuses the person is told it is the sign-in limit and to wait a minute, not that a password
is wrong. Tests: the fake music server answers 429 a number of times (waited out; still found when an owner exists; a persistent 429 is named as such).
