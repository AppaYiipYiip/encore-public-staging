# 25 — Licences and the terms of outside services

> **In short.** Every component Encore ships or runs with its licence and obligation, the outside services it talks to with their terms, the name and trademark question and the provenance of the app code. Several rows say "verify"; the open legal checks are P0-10 and register B-35, and `THIRD_PARTY_NOTICES` does not exist yet.

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
| `cryptography` (Python) | Apache-2.0 OR BSD-3-Clause | server (in use, ADR-R40: the server's Ed25519 key; `pyproject.toml`); wheels for manylinux x86-64 and aarch64 | notice; compatible with GPL-3.0 |
| `cryptography` (Dart) | Apache-2.0 | app (in use, ADR-R40: verifying the server's signature, `server_identity.dart`; also runs on web) | notice |
| Tailscale client | BSD-3-Clause | optional; installed on the Host's computer by `encore funnel on` when it is absent (ADR-R25), not a container | notice |
| Lidarr | GPL-3.0 | optional container (quality tier), unmodified | link source |
| slskd | AGPL-3.0 (*verify*) | optional container, unmodified | link source; unmodified use triggers no extra duty |
| Soularr | *verify* | optional container | as its licence requires |
| NewPipeExtractor (only if X-3 is adopted) | GPL-3.0 | would be linked into the app | fine with GPL-3.0; impossible under the old CC BY-NC-SA licence |
| Illustrations | in-house or CC0 (`16` §2) | app and admin | licence file next to each |

`THIRD_PARTY_NOTICES.md` at the repository root summarises the components. The app's settings open Flutter's open-source licences page,
which lists the full licence text of every Dart package. A notice file generated in CI for the server image is still open (P0-10).

## 2. Outside services Encore talks to

| Service | Used for | Terms in short (*verify the current text*) | Encore's rule |
|---------|----------|--------------------------------------------|---------------|
| YouTube / YouTube Music | finding and streaming songs not on the server | the Terms of Service do not allow downloading except through YouTube's own features | contained source, off switch, honest notice, no accounts, paced (`02` Q1, `04` §5, `09` §5) |
| Deezer API | metadata, ISRC, covers, related artists, charts | free public API; quotas per address; terms forbid some commercial uses | non-commercial project; cache; credit "Metadata from Deezer" in About |
| MusicBrainz / ListenBrainz | identifiers, aliases, similar artists | data under open licences (core data CC0); 1 request/second, a real User-Agent required | not called by any code today (the identifiers are only stored as tags); if it is added: cache 30 days, honest User-Agent (the old recs service was refused with a made-up one) |
| LRCLIB | lyrics | free community service | cache per song; credit |
| Spotify embed pages and data exports | reading a person's own playlists for import | scraping is outside Spotify's developer terms; the data export is the person's own data | link import ≤ 100 songs; the export file is preferred; no Spotify developer app (ADR-R12) |
| Tailscale | the public address | free plan; Funnel has usage limits | the Host's own account; documented limits (`09`) |

## 3. Name and trademarks

"Encore" is a working name (D-5, not now). Before the public release: a trademark and app-name search, and no use of other brands'
logos (Spotify, YouTube) beyond plain words like "Import from Spotify".

## Provenance of the app code

The app's earliest history comes from an earlier open-source player, and almost all of that code has since been rewritten. To check that
nothing of it is still carried over, the lines of 40 or more characters (comments and `import`/`export`/`part` lines left out, white space
normalised) of the earlier player's `lib/` were compared with those of `app/lib`:

* 217 of the 11,074 such lines in `app/lib` also occur in the earlier player, one to eight per file, never more than three in a row.
* Every one of them is ordinary Flutter or Dart idiom that any app written against the same libraries contains: widget arguments
  (`crossAxisAlignment: CrossAxisAlignment.start,`), standard library calls (`SharedPreferences.getInstance()`, `ScaffoldMessenger.of(context)`,
  `WidgetsBinding.instance.addPostFrameCallback`), HTTP client timeouts, the three-line audio-session set-up from that package's own
  documentation, and Android Auto content-style constants that Android fixes.
* The only app file at the same path (`app/lib/main.dart`) has no line in common.

So no third-party notice is due for the app's own code beyond the packages it uses (`THIRD_PARTY_NOTICES.md`). The comparison is a line-by-line
measure: it says nothing about ideas or structure and is not a legal opinion. It is reproduced by listing the matching lines and reading them.
