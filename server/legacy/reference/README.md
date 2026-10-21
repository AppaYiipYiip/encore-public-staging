# Encore reference server

The setup Encore recommends for everyone, proved against a real Navidrome (`tests/check_reference.py`).
Design, options and reasons: `docs/26-reference-server-setup.md`. Plan: `docs/27-plan-perfect-server-and-app.md`.

## Level 0 - music at home, one command

You need a computer that stays on (a mini PC, a NAS, an old laptop) with [Docker](https://docs.docker.com/engine/install/).

```sh
cp .env.example .env        # set MUSIC_DIR to your music folder (and PUID/PGID, TZ)
docker compose up -d
```

Or let a script do the file editing: `bash setup.sh` asks where your music is, fills in `.env`, starts the stack and prints the address to open
(`FUNNEL=1 bash setup.sh` also starts the remote-access sidecar). On Ubuntu Server, `bash host/install-docker-ubuntu.sh` installs Docker from
Docker's own repository first. The guide, `docs/21-server-guide.md`, walks through both.

`docker compose ps` then shows two lines: `navidrome` (running) and `navidrome-init` (`Exited (0)`, which is correct). The second is a
helper that runs once first and gives Navidrome's data folder to the right user; without it Docker would create that folder as root
and Navidrome could not open its database (docs/03, ADR-082).

Open `http://<that computer>:4533`, create the admin account, and sign in from the Encore app. Your music is mounted
**read-only**; the small database (accounts, playlists, likes) is backed up nightly into `data/backups` by default - change the folder, the
count or the time, or switch it off, in `.env`. Backing up the music itself is your decision; nothing here needs a second disk.

## Several people on one server

Each person has their own artists, albums, playlists and likes, and cannot see anyone else's music.

```sh
# before the first start: in .env set  SHARED_LIBRARY_PATH=/music/_shared
# layout:  MUSIC_DIR/_shared/...  (everyone)    MUSIC_DIR/sara/...  MUSIC_DIR/ben/...  (private)
export ND_ADMIN_PASSWORD='...'
python3 encore_user.py --url http://localhost:4533 add sara --music-dir "$MUSIC_DIR"
python3 encore_user.py --url http://localhost:4533 check     # anyone who sees what is not theirs?
```

`add` creates the private library, the account (random password, shown once), and restricts the account to its own
library plus the shared one. If the person's folder is not called like the person (an existing collection mounted as
`owner`, say) use `add <name> --folder owner`. Run it again to repair. Why a tool: Navidrome hands every new account the first library
unless told otherwise, and a library inside another library leaks its music - the tool handles both and proves the result.

## Away from home, nothing to install on phones (Level 1: Tailscale Funnel, no router change)

```sh
FUNNEL=1 bash setup.sh             # asks for a one-time Tailscale key, writes COMPOSE_PROFILES=funnel into .env, starts the sidecar, prints the address
```

(By hand: put `COMPOSE_PROFILES=funnel` in `.env`, then `docker compose up -d`. Compose's own switch means `up`, `down`, `ps` and `logs`
all include the sidecar.)

You need a free Tailscale account (sign in with Google, Microsoft, GitHub or Apple), two one-time clicks in its admin console (HTTPS
certificates, Funnel) and a one-time key (Settings > Keys > Generate auth key; a sign-in link is only good for one minute in a container). After that the address `https://music.<your-tailnet>.ts.net` works from any phone on any network, and nothing is
forwarded in your router. Why this and not Caddy or Cloudflare Tunnel, and its limits: `docs/33-aims-limits-and-remote-access.md`.
Switch off key expiry for the machine in the admin console, or remote access silently stops after 180 days.

**Advanced (Level 1b):** your own name and forwarded ports, with Caddy: set `DOMAIN` and `NAVIDROME_BIND=127.0.0.1` in `.env`,
forward ports 80 and 443 to this computer, then `docker compose --profile https up -d`.

## "Play any song" (optional)

`docker compose --profile kit up -d` adds `encore-fetch` (see `../encore-fetch`).

## Listening together: a Jam (optional)

Add `hub` to `COMPOSE_PROFILES` in `.env` (for example `funnel,people,hub`) and run `docker compose up -d`. It adds `encore-hub`, which holds shared queues in memory and
is shown by the Funnel at `/hub`; it needs the Funnel above and an account per person. No setting is needed. In the app: Home, then **Jam**.

## Measuring what a listener gets away from home

```sh
ENCORE_USER=name ENCORE_PASSWORD=secret python3 tests/measure_remote.py https://music.<your-tailnet>.ts.net --baseline http://<home address>:4533
```

Play-start time, sustained speed and seeking through the public address (and, with `--baseline`, the direct address for comparison);
PASS or FAIL against the targets in `docs/33` (at least 2 Mbit/s sustained, play-start within 3 s, Range requests answered with 206). Credentials
come from the environment and are never printed.

## Checking it yourself

```sh
python3 tests/check_reference.py --navidrome /path/to/navidrome --ffmpeg /path/to/ffmpeg
```

Starts a throw-away Navidrome with exactly the recommended settings and proves: the compose file says what the guide says,
scan, transcoding to Opus, synced lyrics, login rate limit, scheduled backups, the music folder is never written, and the
multi-person isolation (search, artists, folders, streaming by id, playlists, likes).
