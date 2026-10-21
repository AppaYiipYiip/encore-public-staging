#!/usr/bin/env bash
# Starts the Encore server with answers instead of file editing (docs/21 step 2).
#   ./setup.sh                    asks where the music is
#   ./setup.sh /srv/music         the music folder given
#   FUNNEL=1 ./setup.sh           also turns on the remote-access sidecar (docs/33, Tailscale Funnel): it adds
#                                 COMPOSE_PROFILES=funnel to .env, so every later `docker compose` command includes it
#   QUALITY=1 ./setup.sh          also turns on the quality tier (docs/46: Lidarr, slskd and Soularr find the better copy of a song):
#                                 adds the quality profile and makes the keys the programs share. Nothing reaches the Soulseek network
#                                 until the owner switches it on in the admin website.
#   RECS=1 ./setup.sh             also turns on suggestions (docs/47): each person's "Made for you" lists, made at night from what that
#                                 person plays and likes. Only artist and song names go to public catalogues; the owner never sees a list.
#   ADMIN=1 ./setup.sh            also turns on the admin website (docs/50, port 8800, home network only): adds the admin profile and
#                                 the group id of `docker` (so it can open the sign-in window)
# Safe to run again: an existing .env is kept and only filled in where a value is missing.
set -euo pipefail
cd "$(dirname "$0")"

DOCKER=docker
docker info >/dev/null 2>&1 || DOCKER="sudo docker"
if ! $DOCKER compose version >/dev/null 2>&1; then
  echo "Docker with Compose is not installed (or not running). Step 1 of the guide installs it."
  exit 1
fi

[[ -f .env ]] || cp .env.example .env

# Read a value from .env ("" when unset or commented out).
get() { sed -n "s/^$1=//p" .env | tail -n 1; }
# Set a value in .env: replace an active or commented line, or add one.
set_env() {
  local value="$2"
  if grep -qE "^#? *$1=" .env; then
    # Escape what sed treats specially in the replacement (a folder name may hold & or |).
    value="${value//\\/\\\\}"; value="${value//&/\\&}"; value="${value//|/\\|}"
    sed -i -E "0,/^#? *$1=.*/s||$1=$value|" .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

music="${1:-}"
current="$(get MUSIC_DIR)"
if [[ -z $music ]]; then
  # The example file ships /srv/music as a placeholder; only a folder that exists counts as an answer.
  if [[ -n $current && -d $current ]]; then
    music="$current"
  else
    read -r -p "Folder for your music (it is created if missing) [$HOME/music]: " music
    music="${music:-$HOME/music}"
  fi
fi
music="${music/#\~/$HOME}"
mkdir -p "$music" 2>/dev/null || sudo mkdir -p "$music"
music="$(cd "$music" && pwd)"

set_env MUSIC_DIR "$music"
[[ -n "$(get PUID)" ]] || set_env PUID "$(id -u)"
[[ -n "$(get PGID)" ]] || set_env PGID "$(id -g)"
if [[ -z "$(get TZ)" ]]; then
  tz="$(cat /etc/timezone 2>/dev/null || true)"
  [[ -n $tz ]] && set_env TZ "$tz"
fi

# Navidrome (not root) must be able to read the music: say so now instead of showing an empty library later.
owner_uid="$(stat -c %u "$music")"
if [[ "$(get PUID)" != "$owner_uid" && ! -r "$music" ]]; then
  echo "Warning: $music belongs to user id $owner_uid but PUID in .env is $(get PUID); Navidrome may not be able to read it."
fi

# COMPOSE_PROFILES in .env is Compose's own switch for the optional parts. Written here, `docker compose up`, `down`, `ps` and
# `logs` all agree about the sidecar (a plain `down` would otherwise leave a sidecar from an unnamed profile running).
if [[ ${FUNNEL:-0} == 1 ]]; then
  have="$(get COMPOSE_PROFILES)"
  case ",$have," in *,funnel,*) ;; *) set_env COMPOSE_PROFILES "${have:+$have,}funnel" ;; esac
fi
if [[ ${ADMIN:-0} == 1 ]]; then
  have="$(get COMPOSE_PROFILES)"
  case ",$have," in *,admin,*) ;; *) set_env COMPOSE_PROFILES "${have:+$have,}admin" ;; esac
  if [[ -z "$(get DOCKER_GID)" ]]; then
    gid="$(getent group docker | cut -d: -f3 || true)"
    [[ -n $gid ]] && set_env DOCKER_GID "$gid" || echo "Warning: no group called docker here; the admin cannot open the sign-in window without it."
  fi
fi
if [[ ${RECS:-0} == 1 ]]; then
  have="$(get COMPOSE_PROFILES)"
  case ",$have," in *,recs,*) ;; *) set_env COMPOSE_PROFILES "${have:+$have,}recs" ;; esac
fi
if [[ ${QUALITY:-0} == 1 ]]; then
  have="$(get COMPOSE_PROFILES)"
  case ",$have," in *,quality,*) ;; *) set_env COMPOSE_PROFILES "${have:+$have,}quality" ;; esac
  # The keys the programs use to talk to each other: made once, kept in .env (mode 600), never shown.
  rand() { head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; }
  [[ -n "$(get LIDARR_API_KEY)" ]] || set_env LIDARR_API_KEY "$(rand 16)"
  [[ -n "$(get SLSKD_API_KEY)" ]] || set_env SLSKD_API_KEY "$(rand 16)"
  [[ -n "$(get SLSKD_WEB_PASSWORD)" ]] || set_env SLSKD_WEB_PASSWORD "$(rand 12)"
  # A new Soulseek account is made by logging in with a name nobody has: a made-up name and password are all it needs.
  [[ -n "$(get SOULSEEK_USER)" ]] || set_env SOULSEEK_USER "encore-$(rand 4)"
  [[ -n "$(get SOULSEEK_PASSWORD)" ]] || set_env SOULSEEK_PASSWORD "$(rand 12)"
  chmod 600 .env
  if [[ -z "$(get PEOPLE_ADMIN_USER)" ]]; then
    echo "Note: the quality tier needs the music server's administrator login in .env (PEOPLE_ADMIN_USER and PEOPLE_ADMIN_PASSWORD, the"
    echo "same as the people service uses), to see where songs are kept. It stays idle until they are there."
  fi
fi
funnel_on=0
case ",$(get COMPOSE_PROFILES)," in *,funnel,*) funnel_on=1 ;; esac
if ((funnel_on)); then
  # Every guest arrives from the sidecar's address; without these, one stranger's wrong guesses lock everyone out (docs/33, T5).
  [[ -n "$(get PROXY_TRUSTED_SOURCES)" ]] || set_env PROXY_TRUSTED_SOURCES "172.16.0.0/12"
  if [[ -z "$(get PROXY_USER_HEADER)" ]]; then
    secret="$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    set_env PROXY_USER_HEADER "X-Encore-$secret"
  fi

  # Joining the Tailscale account. A sign-in link is only good for ONE MINUTE in a container (Tailscale gives up after 60 s and
  # prints a new one), so the easy, reliable way is a one-time key pasted here. Asked only while the sidecar is not connected
  # (a state file proves nothing: Tailscale writes one on its very first start, before anybody has signed in).
  ts_now="$($DOCKER inspect -f '{{.State.Health.Status}}' encore-tailscale 2>/dev/null || echo none)"
  if [[ -z "$(get TS_AUTHKEY)" && $ts_now != healthy ]]; then
    echo
    echo "Remote access: this computer must join your Tailscale account (free)."
    echo "Easiest: open https://login.tailscale.com/admin/settings/keys , press 'Generate auth key', keep the options as they are,"
    echo "copy the key (it starts with tskey-auth-) and paste it below. It is used once and then removed from this computer."
    echo "If this computer has already joined, or you prefer a sign-in link (you must open it within one minute), just press Enter."
    key=""
    read -r -s -p "Key (typing is hidden): " key || true
    echo
    if [[ -n $key ]]; then
      set_env TS_AUTHKEY "$key"
      chmod 600 .env
    fi
  fi
fi

first_run=1
database="$(get DATA_DIR)"; database="${database:-./data}/navidrome/navidrome.db"
[[ -f $database ]] && first_run=0

echo "Starting the server (the first time this downloads about 100 MB) ..."
$DOCKER compose up -d

echo "Waiting for Navidrome to answer ..."
for _ in $(seq 1 60); do
  state="$($DOCKER inspect -f '{{.State.Health.Status}}' navidrome 2>/dev/null || echo starting)"
  [[ $state == healthy ]] && break
  sleep 3
done
if [[ $state != healthy ]]; then
  echo "Navidrome did not become healthy. Look at:  $DOCKER compose logs navidrome"
  exit 1
fi

ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
if ((first_run)); then
  echo "The server is running. Open  http://${ip:-<this computer>}:4533  and create the administrator account."
else
  echo "The server is running at  http://${ip:-<this computer>}:4533"
fi
echo "Music folder: $music   (copy songs in; the server notices within an hour, or press 'Scan' in its web page)"
if ((funnel_on)); then
  echo
  echo "Remote access (Tailscale Funnel): checking ..."
  link=""
  ts_state=starting
  for _ in $(seq 1 25); do
    ts_state="$($DOCKER inspect -f '{{.State.Health.Status}}' encore-tailscale 2>/dev/null || echo starting)"
    [[ $ts_state == healthy ]] && break
    sleep 3
  done
  if [[ $ts_state == healthy ]]; then
    status="$($DOCKER exec encore-tailscale tailscale --socket=/tmp/tailscaled.sock status --peers=false --json 2>/dev/null || true)"
    name="$(printf '%s' "$status" | sed -n 's/.*"DNSName": *"\([^"]*\)".*/\1/p' | head -n 1 | sed 's/\.$//')"
    echo "Connected. Your address from anywhere:  https://${name:-<see the Machines page of Tailscale>}"
    # An invitation is a link on this address (docs/35): remember it for the people service, which refuses to make one without it.
    if [[ -n $name ]]; then
      set_env PUBLIC_URL "https://$name"
    fi
    echo "(If it does not open yet: the very first time it can take up to 10 minutes. Step 4 of the guide has the two clicks.)"
    # The one-time key did its job (the machine keeps its own identity in data/tailscale); do not leave a secret lying around.
    if [[ -n "$(get TS_AUTHKEY)" ]]; then
      set_env TS_AUTHKEY ""
      echo "(The key was removed from .env.)"
    fi
  elif [[ -n "$(get TS_AUTHKEY)" ]]; then
    echo "Not connected yet, although a key was given. The key may be wrong, used up or expired. Look at:  $DOCKER compose logs tailscale"
    echo "Make a new key and run  FUNNEL=1 bash setup.sh  again."
  else
    # No key: Tailscale prints a sign-in link and gives up on it after one minute, then prints a new one. The newest is the valid one.
    link="$($DOCKER compose logs --no-log-prefix tailscale 2>&1 | grep -o 'https://login.tailscale.com/[^ ]*' | tail -n 1 || true)"
    if [[ -n $link ]]; then
      echo "Open this link NOW (it changes every minute), sign in, and press Connect:"
      echo "  $link"
      echo "If it has changed, run  FUNNEL=1 bash setup.sh  again for the newest one; a key (see above) avoids the rush."
    else
      echo "Not connected yet. Look at:  $DOCKER compose logs tailscale"
    fi
  fi
fi
