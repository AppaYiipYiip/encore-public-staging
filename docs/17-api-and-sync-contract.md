# 17 — The app ↔ server contract (API, live channel, sync, errors, versions)

Why this page exists: `tasks/P2` had only an endpoint sketch. Without fixed conventions every agent invents its own error format,
ids and retry rules, which is how the old project got six services with six habits. Everything here is binding for the Encore
server and every client (Android now, web/PC later). The machine-readable form is **planned, not built**: an `openapi.json` written into the repository
by the server and checked by a server test (`11` ADR-R41 T5). Today there is no such file and no such check, and since S1 (B19) the running server no longer serves `/openapi.json`.

## 1. Conventions

| Topic | Rule |
|-------|------|
| Base | One origin per server; all Encore routes under `/encore/api/v1/…`; the live channel at `/encore/live`; audio at `/encore/stream/…` |
| Auth | `Authorization: Bearer <device token>` (P3-03). Never in the URL, except audio URLs, which use a signed `?sig=` (6 hours for a song address, 7 days for a cover address: `auth.py` `STREAM_URL_TTL_S`, `COVER_PASS_TTL_S`) because players cannot set headers everywhere |
| Ids | Server-made ids are opaque strings with a type prefix: `sr_` song ref, `pl_` playlist, `pe_` playlist entry, `dv_` device, `im_` import, `jm_` Jam. Clients create ids for things they create (`pl_`/`pe_` as ULIDs) so an offline create can be retried without duplicates |
| Time | All timestamps are UTC milliseconds from the server clock (`at`); the server returns `serverTime` in every response so clients can measure their clock offset |
| Writes | Every write is **idempotent**: `Idempotency-Key` header (a ULID per user action); the server remembers keys for 7 days |
| Lists | Cursor pagination: `?limit=` (max 500) and `?cursor=`; responses `{items, nextCursor}` |
| Changes | `GET /library/changes?since=<cursor>` returns everything changed for this person since the cursor, including deletions (tombstones), in order |
| Errors | One shape everywhere: `{"error": {"code": "song_unavailable", "message": "This song isn't available in your country.", "retryable": false, "retryAfterMs": null, "details": {}}}`; `message` is a plain sentence the app may show as is; `code` is for logic |
| Rate limits | `429` with `retryAfterMs`; per person and per device |
| Versions | `GET /encore/api/v1/info` → `{apiVersion: "1.0", minAppVersion: "0.1.0", serverVersion, features[]}` (today's values); additive changes bump the minor; a breaking change is a new `/v2` while `/v1` keeps working for **two app releases**; the app refuses to run against a server whose `apiVersion` major it does not know and says "Update Encore" (or "Ask the owner of <the server's name> to update the server", with no person's name: `design/03`, designed, not built). `info` also carries `youtube` (`{state: ok|resting|off, resumesInSec}`) and, on a server that keeps its own yt-dlp fresh (ADR-R39), `tools: {ytDlp: {running, pending, state: ok|degraded}}`: `pending` is a newer version that waits for a quiet moment to be switched to, `degraded` means songs from YouTube are not working right now. Built (ADR-R40, decided 2026-10-23): `info` always carries `serverId` and `publicKey`, and `GET /info?challenge=<nonce>` adds a signature over the nonce and the id (`identity.py`); a signed-in `GET /encore/api/v1/server` returns `{serverId, name, addresses: [{kind: home|away, url}]}` |

## 2. Error codes (the closed list; new codes need a doc change)

`unauthorized`, `forbidden`, `not_found`, `conflict` (stale revision), `validation`, `rate_limited`, `song_unavailable`
(`details.reason`: `not_found` | `region_blocked` | `age_restricted` | `removed`), `source_busy` (YouTube pushing back; retryable),
`source_unreachable`, `storage_full`, `server_busy`, `upstream_timeout`, `federation_disabled`, `peer_unreachable`, `internal`.
Each has one plain message, owned by the server (`server/encore_server/encore_server/errors.py`; English only today), so all clients say the same thing.

## 3. Endpoint inventory (v1)

| Module | Endpoints |
|--------|-----------|
| info/accounts | `GET info` · `POST auth/login` · `POST auth/pair` (Host's QR pairing) · `POST auth/logout` · `GET me` · `PATCH me` · `GET me/devices` · `DELETE me/devices/{dv}` |
| catalogue | `GET search?q=&types=` · `POST refs/resolve` · `GET refs/{sr}` · `GET albums/{id}` · `GET artists/{id}` · `POST refs/{sr}/report` (wrong song, `19` §5) |
| library | `GET library/changes` · `PUT/DELETE likes/{sr}` · `PUT/DELETE saved-albums/{id}` (a release the server does not hold yet names its songs, see "Saving a release" below) · `PUT/DELETE follows/{artistId}` · playlists CRUD · `POST playlists/{pl}/entries` · `DELETE …/entries` · `PUT …/order` · `POST plays` |
| playback | `GET playback` · `PUT playback` (with `rev`) · `POST playback/claim` · `POST playback/transfer` |
| devices | `GET devices` · `POST devices/{dv}/command` · `PUT devices/{dv}` (name, shared, always-ready) |
| imports | `POST imports` · `GET imports/{im}` · `POST imports/{im}/stop` · `GET imports` |
| downloads | `POST downloads/prepare` (server-side transcode/keep before the phone downloads) · `GET downloads/manifest?since=` |
| recs | `GET recs/home` · `GET recs/radio?seed=` · `POST recs/feedback` |
| social | `GET friends` · `POST friends/code` · `POST friends/accept` · `DELETE friends/{id}` · `GET activity` · `PUT me/sharing` |
| jam | `POST jams` · `POST jams/join` (code) · `POST jams/{jm}/commands` · `DELETE jams/{jm}/me` |
| people (owner) | `GET people` · invitations · password reset · lock/remove · storage per person (counts) |
| problems | `POST problems` (opt-in reports) |
| federation (server-to-server, signed) | `/encore/federation/v1/…`: `well-known`, friend requests, Jam join/relay, Jam stream grants, shares (`13` §4–5) |

## 4. The live channel (`/encore/live`, websocket)

* One connection per running app; authenticated by the device token in the first message; the server sends `hello {serverTime,
  cursor}`; ping/pong every 25 s; reconnect with jittered back-off (1, 2, 4 … 30 s); on reconnect the app calls `library/changes`
  and `GET playback`, so no event is ever needed to be correct (events only make things faster). The server ends a connection whose device is signed out, revoked,
  locked or removed: it closes the socket with code **4401** within a moment (built, S3 B5: `live.py` `Hub.end`), and the app takes 4401 as "token refused" (`31` CN-23).
* Events (server → app): `library.changed {cursor}`, `playback.changed {state, rev}`, `device.takeover {by}`, `device.command
  {command, rev}`, `device.state {dv, state}`, `import.progress {im, counts}`, `jam.state {…}`, `friend.request {…}`,
  `activity {…}`, `server.notice {code, message}`.
* Messages from the app on the socket are only `device.state` reports and Jam clock pings; everything else goes through HTTP (one
  write path, idempotent, easy to retry).

## 5. Sync and conflicts (offline edits on several devices)

* The phone keeps an **outbox** of operations, not snapshots: `like(sr)`, `unlike(sr)`, `addEntries(pl, [sr], after)`,
  `removeEntries(pl, [pe])`, `move(pl, pe, after)`, `rename(pl, name)`, `deletePlaylist(pl)`.
* The server applies operations in arrival order; each is meaningful on its own, so two devices' offline edits **merge**: adds from
  both survive; a removed entry stays removed; a move of a removed entry is dropped; renames are last-writer-wins by server arrival;
  operations on a deleted playlist are dropped and reported (`conflict`) so the phone shows "That playlist was deleted on another
  device".
* **Saving a release (D-21, decided by the advisor 2026-10-30).** On an Encore server "Add to library" and "Download" on a catalogue release are server operations, and the screen shows only what the server confirms. `PUT saved-albums/{id}` takes an optional body `{"refs": [song ids]}` (at most 500; the ids the phone got from `refs/resolve`). One call: the save is recorded (the change feed delivers it), and the server **keeps those songs in the background, first in line, whether or not the phone stays** (the thin-client rule: a web client needs the same). All or nothing: a song the server does not know refuses the whole call, `404 not_found`, "That song is not known to this server." with the id in `details`, and nothing is saved. Safe to repeat: the second call changes nothing and queues nothing twice (a song whose keep failed is asked for again). The answer is `{changed, cursor, keep: {songId: {state: queued|keeping|kept|failed|none|unavailable[, reason]}}}`, the states of `GET refs/{id}/keep`. A download is this call plus a pin on the phone, written at once so it survives the app being killed. Likes stay likes: saving an album never fills Liked Songs.
* Likes are a set; like/unlike conflicts resolve by **arrival order at the server** (decided 2026-10-23, `34` G-1: with a live connection two phones of one person see the real order within about 2.5 s; the like's own time only keeps the order of Liked Songs). Every pair of operations, with its test, is in **`34`**.
* Playback state uses `rev` (optimistic concurrency): a write with an old `rev` gets `conflict` and the current state.
* Journey **J-15** (`14` §3) is the acceptance test.

## 6. What the phone stores (and what it never needs the network for)

The phone mirrors the person's library (refs it uses, likes, playlists, saved albums, follows, history for Year in Music), the
covers it has shown (bounded cache) and everything downloaded (never evicted). It does **not** mirror the server's whole catalogue;
search of songs not in the person's library needs the server.

## 7. Timeouts and retries (one table for every client)

| Call | Timeout | Retry |
|------|---------|-------|
| Any read (library, info) | 8 s | 3× with back-off, then show the cached data quietly |
| Writes (outbox) | 15 s | forever with back-off (outbox), stop on non-retryable codes |
| Search | 3 s | none (the next keystroke retries) |
| Stream start | 10 s to first audio byte | 1 retry, then the plain error |
| Live channel connect | 10 s | back-off up to 30 s, forever while the app runs |
