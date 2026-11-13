# Third-party notices

Encore itself is GPL-3.0-or-later (`LICENSE`). It uses, ships or runs the components below. This is a summary; the full table, the outside
services and the checks that are still open are in [`docs/25-licences-and-third-party-terms.md`](docs/25-licences-and-third-party-terms.md).

## In the app

| Component | Licence |
|-----------|---------|
| Flutter and the Dart SDK | BSD-3-Clause |
| Dart packages listed in `app/pubspec.yaml` (audio, database, state, HTTP, notifications, downloads, QR, colours, secure storage, ...) | mostly MIT, BSD-3-Clause or Apache-2.0; the full licence text of every package is shown in the app under Settings, on Flutter's open-source licences page |
| `cryptography` (Dart) | Apache-2.0 |
| Figtree typeface (`app/assets/fonts`) | SIL Open Font Licence 1.1, text in `app/assets/fonts/OFL.txt` |

## In the server

| Component | Licence |
|-----------|---------|
| FastAPI, Starlette, uvicorn | MIT, BSD-3-Clause, BSD-3-Clause |
| `cryptography` (Python) | Apache-2.0 or BSD-3-Clause |
| mutagen (audio tags) | GPL-2.0-or-later (compatible with GPL-3.0) |
| yt-dlp | The Unlicense |
| ytmusicapi | MIT |
| Deno (runs yt-dlp's challenges) | MIT |
| FFmpeg (Debian package in the server image) | LGPL-2.1+ or GPL, depending on the Debian build; its source is available from Debian |

## Programs Encore talks to or can run beside, unmodified, as separate containers

| Program | Licence | How |
|---------|---------|-----|
| Navidrome | GPL-3.0 | the music server Encore builds on, talked to over HTTP |
| Lidarr | GPL-3.0 | optional, over HTTP |
| slskd | AGPL-3.0 | optional, over HTTP; unmodified |
| Soularr | licence to be confirmed (open check in `docs/25`) | optional |
| Tailscale client | BSD-3-Clause | optional, for the public address |

Names such as Spotify, YouTube, Deezer, LRCLIB, MusicBrainz, Navidrome and Tailscale belong to their owners; they appear here and in the documents
only to say what Encore works with.
