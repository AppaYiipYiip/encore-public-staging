# Changelog

User-visible changes, newest first. One line per change, in plain words.

## Unreleased

Everything below is built and tested but **not yet walked on a phone** (`docs/tasks/RELEASE-CANDIDATE.md`, the definition of pass); nothing here is released.

* The music server's door on the internet now slows wrong passwords like every other door (a stranger could try 65 a second); an app that sends only a plain password cannot sign in through the public address.
* A server that does not answer no longer makes the player skip songs: it waits and plays on when the server is back.
* One calm line, once, when the phone is offline or the server is away; "another server answers" gets its own line.
* A tap plays the full song, never a silent 30-second preview; the build says which build it is (About and Diagnostics).
* Downloads: a downloaded album or playlist is one entry that survives a restart; removing a playlist takes its songs off the phone at once; a song two downloaded releases share stays until both are gone; a per-song Download and Remove download in the song menu.
* Add to library and Download on a release are done by the server and show only what it confirmed.
* Long-press and a three-dots menu on songs and Library rows; one "my music / whole server" switch.
* Home offers Jam only where the server has Jam; the avatar opens a drawer; "Share what I'm listening to" only where it works; no speed control or Private listening in the player.
* Invitations: the link opens a page in the browser, a join whose answer was lost can be repeated, and a removed or locked person's phones, songs and pictures stop working.
* Wrong passwords are slowed and never lock an account; request sizes are limited; the server no longer publishes its route list.
* The first sign-in finds out within seconds that it is an Encore server; "Invite someone" and People appear once the server is known.
* The server installs in one command, backs itself up every night, and updates its own yt-dlp safely.
* The repository was reset: a clean history, GPL-3.0 licence.
