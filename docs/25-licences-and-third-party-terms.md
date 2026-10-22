# 25 — Licences and the terms of outside services

Why: Encore will be public (GPL-3.0, D-1 default). Every part it ships or depends on must be compatible, credited, and its terms
understood; otherwise the first public release can be taken down. Items marked *verify* must be checked at the source in task P0-05 /
P5-06 and this table corrected.

## 1. What Encore ships or runs

| Component | Licence | How Encore uses it | Obligation |
|-----------|---------|--------------------|------------|
| Flutter, Dart SDK | BSD-3-Clause | builds the app | notice in the app's licence screen |
| Dart packages (just_audio, audio_service, drift, riverpod, dio, cached_network_image, flutter_local_notifications, workmanager, qr_flutter, background_downloader, flutter_secure_storage, palette_generator, …) | mostly MIT/BSD (*verify each*; `flutter pub deps` + a licence check in CI) | linked into the app | Flutter's built-in licence page (`showLicensePage`) lists them all automatically |
| Figtree font | SIL Open Font Licence 1.1 | app and admin | keep `OFL.txt` with the font |
| Navidrome | GPL-3.0 | separate container, unmodified, talked to over HTTP | name it and link its source in the docs; no linking, so no effect on Encore's licence |
| yt-dlp | Unlicense (public domain) | inside the server image | none (credit anyway) |
| ytmusicapi | MIT | inside the server image | notice |
| Deno | MIT | inside the server image (yt-dlp's JavaScript challenges) | notice |
| FFmpeg | LGPL-2.1+ or GPL depending on the build (*verify the build used*) | inside the server image (remux, loudness, transcoding) | notice + source offer for the exact build |
| mutagen (tags) | GPL-2.0-or-later | server | compatible with GPL-3.0 |
| FastAPI / Starlette / uvicorn | MIT / BSD-3 / BSD-3 | server | notice |
| Tailscale client | BSD-3-Clause | optional sidecar container | notice |
| Lidarr | GPL-3.0 | optional container (quality tier), unmodified | link source |
| slskd | AGPL-3.0 (*verify*) | optional container, unmodified | link source; unmodified use triggers no extra duty |
| Soularr | *verify* | optional container | as its licence requires |
| NewPipeExtractor (only if X-3 is adopted) | GPL-3.0 | would be linked into the app | fine with GPL-3.0; impossible under the old CC BY-NC-SA licence |
| Illustrations | in-house or CC0 (`16` §2) | app and admin | licence file next to each |
| Test music in the repository | Creative Commons (*per album*) | test assets (`24` §2) | credit per licence (CC-BY needs attribution; avoid NC/ND for anything redistributed) |

The server image gets a `THIRD_PARTY_NOTICES` file generated in CI; the app's About → "Open-source licences" shows Flutter's page plus
a short list of the server-side parts.

## 2. Outside services Encore talks to

| Service | Used for | Terms in short (*verify the current text*) | Encore's rule |
|---------|----------|--------------------------------------------|---------------|
| YouTube / YouTube Music | finding and streaming songs not on the server | the Terms of Service do not allow downloading except through YouTube's own features | contained source, off switch, honest notice, no accounts, paced (`02` Q1, `04` §5, `09` §5) |
| Deezer API | metadata, ISRC, covers, related artists, charts | free public API; quotas per address; terms forbid some commercial uses | non-commercial project; cache; credit "Metadata from Deezer" in About |
| MusicBrainz / ListenBrainz | identifiers, aliases, similar artists | data under open licences (core data CC0); 1 request/second, a real User-Agent required | cache 30 days; honest User-Agent (the old recs service was refused with a made-up one) |
| LRCLIB | lyrics | free community service | cache per song; credit |
| Spotify embed pages and data exports | reading a person's own playlists for import | scraping is outside Spotify's developer terms; the data export is the person's own data | link import ≤ 100 songs; the export file is preferred; no Spotify developer app (ADR-R12) |
| Tailscale | the public address | free plan; Funnel has usage limits | the Host's own account; documented limits (`09`) |

## 3. Name and trademarks

"Encore" is a working name (D-5, not now). Before the public release: a trademark and app-name search, and no use of other brands'
logos (Spotify, YouTube) beyond plain words like "Import from Spotify".

## Provenance of the app code (checked 2026-10-22)

The app began as a fork of another player and was rewritten; its licence (CC BY-NC-SA 4.0) is not a software licence and is why Encore is
GPL-3.0 (D-1). Facts, measured against the original project's `lib/` in the archived history (`releases-archive/`, not in this repository):

* The only app file at the same path is `app/lib/main.dart` (every Flutter app has one): 4 lines here, 762 there, no line in common.
* Lines of 40 or more characters (comments and imports left out): 14,915 in `app/lib`, of which 200 (1.3%) also appear in the original,
  spread over many files at one to eight lines each (the most in a single file: 8 of 138).
* This says nothing about ideas or structure, and a line-by-line match is not a legal test. Whether credit or a licence notice is still due
  for those lines is the owner's decision; if it is, it goes in `THIRD_PARTY_NOTICES` (P0-10).
