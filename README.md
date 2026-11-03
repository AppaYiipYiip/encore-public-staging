# Encore

**A free music server you install on any spare computer, plus an Android app that plays almost any song instantly, keeps the music you
love on your own disk, and lets your family and friends listen too. No subscription.**

> Status: early development (version 0.x). The server and app work for a small group of testers; the public release is not out yet.

**Want to change something?** Read [`docs/guides/getting-started-for-developers.md`](docs/guides/getting-started-for-developers.md) first: a map of the repository, your first hour, and how a change goes.

## What it does

* Plays your own music files from your own server (powered by [Navidrome](https://www.navidrome.org)).
* Plays songs you don't have yet, in about two seconds, and keeps the ones you save.
* Brings your playlists over from Spotify or YouTube Music in seconds.
* Resume a song at the same second on another device, and control one device from another (planned: the server already keeps the playback state, the app does not offer it yet).
* Listen together with friends (Jam), also with friends who run their own Encore server (planned: the old Jam is not on the new server yet).
* Works away from home without opening router ports (Tailscale Funnel: proved once on the owner's own server on 2026-11-03, see `docs/evidence/c05`; not yet from a phone on mobile data).

## How it is organised

| Folder | What it is |
|--------|-----------|
| [`app/`](app) | The Android app (Flutter) |
| [`server/`](server) | The Encore server: `server/encore_server` is the one program; `server/legacy/` still holds the older separate services (see the roadmap) |
| [`packages/encore_session`](packages/encore_session) | Shared Dart rules for listening together |
| [`tools/`](tools) | Developer scripts: the check gate, emulator journeys, measurements |
| [`docs/`](docs) | Product, design, architecture, roadmap, tasks. **Start with [`docs/README.md`](docs/README.md)** |

## Working on Encore

Read [`AGENTS.md`](AGENTS.md) (it applies to people and to coding agents alike), then pick a task in [`docs/tasks/`](docs/tasks).
Run the checks before every commit: `powershell tools/check.ps1 -Quick` (add `-Server` for the server suites).

## Licence

GPL-3.0-or-later, see [`LICENSE`](LICENSE). Third-party components and their licences: [`docs/25-licences-and-third-party-terms.md`](docs/25-licences-and-third-party-terms.md).
