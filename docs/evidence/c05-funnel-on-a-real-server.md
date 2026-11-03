# c05: `encore funnel on` on a real server, a real Tailscale sign-in, 2026-11-03

First real run of the away-from-home address (ADR-R25, ADR-R40). The owner's own server (the VM he installed from the guide, Ubuntu 26.04, 3 GiB),
the image built from `main` at `589d8e4` (2026-11-03 16:01 UTC), Tailscale installed by the command itself, the sign-in done by the owner in his
browser. The public name is `<machine>.<tailnet>.ts.net` and is not written here (docs/06: nothing of the owner's accounts belongs in the repository).
Addresses of people and machines are not written either.

## What happened, in order

| Step | Result |
|---|---|
| Read-only look at the server | image built 26 Oct (before the security fixes S1/S3), healthy, no Tailscale, nightly backup current |
| A hole found before switching on (AUDIT A-18) | the music server's door under `/rest` had no limit on wrong passwords (40 wrong sign-ins in 0.6 s on the dev server, none refused); fixed in PR #127 and published |
| `sudo encore update` | a backup first (`before-update` copy of `compose.yaml` kept), new image (created 16:01 UTC), both containers healthy |
| Guard checked on the updated server from a pretend internet address | the music server's own pages 404, five wrong sign-ins 401 then 429, no login 401 |
| `sudo encore funnel on` under a terminal | asked to install Tailscale (yes), printed a sign-in link, the owner signed in, the command went on by itself and printed `Away from home: https://<machine>.<tailnet>.ts.net`. No second link about HTTPS or Funnel was printed |

## What was checked through the public address (from the owner's PC, over the internet and back in through Tailscale)

| Check | Expected | Got |
|---|---|---|
| `GET /encore/api/v1/info` | 200 with the server's id | 200, the server's name, id and public key |
| `/openapi.json`, `/app/`, `/auth/login`, `/api/user` | 404 (the music server's own pages stay on the home network) | 404 for all four |
| `GET /rest/ping` with no login | 401 | 401, "Sign in with a token login" |
| websocket upgrade on `/encore/live` | 101 | `HTTP/1.1 101 Switching Protocols` |
| eight wrong sign-ins at `/rest/ping`, one made-up name | five refused as wrong, then slowed | 401, 401, 401, 401, 401, 429, 429, 429 |
| **Which address the server counts a wrong guess against** (the log line added in B12b, compared with the PC's public address from `curl ifconfig.me`) | the visitor's own address, not the proxy's | **the same address as the PC's**: Funnel forwards the visitor's address in `X-Forwarded-For` and the server reads it (AUDIT B11 verified). Every internet visitor therefore has a limit of their own |

## What this run does not prove

* A phone on mobile data (the owner's PC went out and in through the same home line); an invitation opened from a phone on another network.
* X-7: the live connection through Funnel for two hours; reconnecting after the phone changes network.
* That the app learns the away address from the server (`GET /encore/api/v1/server` needs a login; nobody signed in during this run), and that an older app build copes with the new server.
* Tailscale's own limits: the sign-in key expires (180 days), Funnel's bandwidth is not published, and Tailscale could change or end Funnel.

## Things to know about the public name and the account

* The name contains the machine's name and a random tailnet id, not the owner's e-mail address. Tailscale's documentation says the names of nodes with HTTPS
  certificates appear in the public certificate logs, so the fact that this address exists is discoverable; nothing behind it is, without a login.
* The server joined the owner's existing Tailscale account, which already has other devices. Tailscale's default policy lets the devices of one account
  reach each other, so the Encore server can reach those devices and they can reach it. Only the Encore port is on the internet (Funnel), but if the
  Encore server were ever taken over, the other devices on the account would be one hop away. Tags and an access policy in the Tailscale admin console
  can forbid that; it is the owner's account and his decision.
* An invitation gives a friend the Encore app and this address. The friend never joins the owner's Tailscale account and needs no Tailscale.
