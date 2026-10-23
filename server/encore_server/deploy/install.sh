#!/usr/bin/env bash
# Encore installer (docs/tasks P3-05): installs the music server and the Encore server on this computer.
#
#   sudo bash install.sh                     asks what it needs (the owner's name and password, where the music is)
#   sudo bash install.sh --yes --owner NAME  asks nothing it can do without; the password comes from ENCORE_OWNER_PASSWORD
#
# Running it again is safe: what is installed is kept and brought up to date. Everything it does is written to /var/log/encore-install.log;
# nothing secret is printed or logged. It never touches other containers, the music folder's files, or any firewall rule except (when the
# computer's firewall is on) allowing the one port Encore uses.
set -Eeuo pipefail

DIR=/opt/encore
IMAGE=ghcr.io/appayiipyiip/encore-server
TAG=main
PORT=4533
MUSIC_DIR=/srv/music
SERVER_NAME=""
OWNER=""
YES=0
LOG=/var/log/encore-install.log
OWNER_PASSWORD="${ENCORE_OWNER_PASSWORD:-}"

# ---------------------------------------------------------------------------------------------------------------- how it talks

if [ -t 1 ]; then GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; OFF=$'\033[0m'; else GREEN=""; RED=""; DIM=""; BOLD=""; OFF=""; fi

say() { printf '%s\n' "$*"; }
ok() { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$*"; }
note() { printf '  %s%s%s\n' "$DIM" "$*" "$OFF"; }
die() {
    printf '\n  %s✗ %s%s\n' "$RED" "$*" "$OFF" >&2
    printf '  %sThe details are in %s. Running the same command again is safe.%s\n\n' "$DIM" "$LOG" "$OFF" >&2
    exit 1
}
log() { printf '%s\n' "$*" >>"$LOG"; }
T0=$(date +%s)
since() { echo $(($(date +%s) - T0)); }

trap 'die "Something went wrong at line $LINENO of the installer."' ERR

usage() {
    cat <<'EOF'
Usage: sudo bash install.sh [options]

  --yes                  do not ask; answer yes to installing what is missing
  --owner NAME           the owner's username (3 to 32 letters, digits, . - _)
  --owner-password-file F  read the owner's password from the first line of file F (for installs nobody sits at)
  --name TEXT            the server's name, shown to people you invite (default: this computer's name)
  --music-dir PATH       where the music is, or will be (default /srv/music)
  --port N               the port the apps connect to (default 4533)
  --dir PATH             where Encore keeps its files (default /opt/encore)
  --image NAME           the server image (default ghcr.io/appayiipyiip/encore-server)
  --tag TAG              the image version (default main)

The owner's password is asked for, or read from a file (--owner-password-file), or from ENCORE_OWNER_PASSWORD. For a private image, sign in to
GitHub first with  gh auth login --scopes read:packages  (the installer finds that login even under sudo), or give a token that may read
packages in GH_TOKEN / GHCR_TOKEN.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --yes | -y) YES=1 ;;
        --owner) OWNER="${2:?--owner needs a name}"; shift ;;
        --owner-password-file) OWNER_PASSWORD="$(head -n 1 "${2:?--owner-password-file needs a file}")"; shift ;;
        --name) SERVER_NAME="${2:?--name needs a text}"; shift ;;
        --music-dir) MUSIC_DIR="${2:?--music-dir needs a path}"; shift ;;
        --port) PORT="${2:?--port needs a number}"; shift ;;
        --dir) DIR="${2:?--dir needs a path}"; shift ;;
        --image) IMAGE="${2:?--image needs a name}"; shift ;;
        --tag) TAG="${2:?--tag needs a version}"; shift ;;
        --help | -h) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

# ---------------------------------------------------------------------------------------------------------------- questions

TTY=""
if [ -t 0 ]; then TTY=/dev/stdin; elif { : </dev/tty; } 2>/dev/null; then TTY=/dev/tty; fi

ask() { # ask "question" default -> answer (default when the person just presses Enter, or when nobody can be asked)
    local question="$1" default="${2:-}" answer=""
    if [ -z "$TTY" ] || [ "$YES" = 1 ]; then printf '%s' "$default"; return; fi
    read -r -p "  $question${default:+ [$default]} " answer <"$TTY" || true
    printf '%s' "${answer:-$default}"
}

ask_yes() { # ask_yes "question" -> succeeds on yes; yes by default
    [ "$YES" = 1 ] && return 0
    [ -z "$TTY" ] && return 1
    local answer=""
    read -r -p "  $1 [Y/n] " answer <"$TTY" || true
    case "${answer:-y}" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

ask_secret() { # ask_secret "question" -> the answer, not shown on the screen
    local answer=""
    [ -z "$TTY" ] && return 1
    read -r -s -p "  $1 " answer <"$TTY" || true
    printf '\n' >&2
    printf '%s' "$answer"
}

# ---------------------------------------------------------------------------------------------------------------- the checks

mkdir -p "$(dirname "$LOG")"
: >>"$LOG"
chmod 600 "$LOG"
log "=== $(date -u +%FT%TZ) install.sh $*"

say ""
say "  ${BOLD}♪  Encore: installing your music server${OFF}"
say ""

[ "$(id -u)" = 0 ] || die "This needs to run as the administrator of this computer: use  sudo bash install.sh"

# shellcheck disable=SC1091
. /etc/os-release 2>/dev/null || die "This does not look like a Linux computer Encore knows. It installs on Ubuntu or Debian for now."
case " ${ID:-} ${ID_LIKE:-} " in
    *" ubuntu "* | *" debian "*) ;;
    *) die "This computer runs ${PRETTY_NAME:-an unknown system}. Encore installs on Ubuntu or Debian for now." ;;
esac

case "$(uname -m)" in
    x86_64 | amd64) ;;
    *) die "This computer is a $(uname -m) one. Encore installs on 64-bit Intel or AMD computers for now." ;;
esac

MEM_MB=$(awk '/^MemTotal:/ {print int($2/1024)}' /proc/meminfo)
[ "${MEM_MB:-0}" -ge 1800 ] || die "This computer has ${MEM_MB} MB of memory; Encore needs at least 2 GB."

mkdir -p "$(dirname "$DIR")"
FREE_GB=$(df --output=avail -BG "$(dirname "$DIR")" | tail -1 | tr -dc '0-9')
[ "${FREE_GB:-0}" -ge 6 ] || die "There is ${FREE_GB} GB of free space where Encore keeps its files; it needs at least 6 GB."
ok "This computer: 64-bit Intel/AMD, $(((MEM_MB + 512) / 1024)) GB memory, ${FREE_GB} GB free"

command -v curl >/dev/null 2>&1 || { apt-get update -qq >>"$LOG" 2>&1 && apt-get install -y -qq curl ca-certificates >>"$LOG" 2>&1; } || die "Encore needs curl and could not install it."
case "$(curl -s -m 15 -o /dev/null -w '%{http_code}' https://ghcr.io/v2/ 2>>"$LOG" || true)" in
    200 | 401) ;;
    *) die "No internet connection: check the cable or the Wi-Fi and run the same line again." ;;
esac

if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${PORT}\$" && ! [ -f "$DIR/.env" ]; then
    die "Something else already uses port ${PORT} on this computer. Stop it, or run this again with  --port 4540  (any free number)."
fi

# ---------------------------------------------------------------------------------------------------------------- what is asked

FRESH=1
[ -f "$DIR/.env" ] && FRESH=0

env_value() { grep -E "^$1=" "$DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- || true; }

if [ "$FRESH" = 0 ]; then
    note "Encore is already installed here: it is kept and brought up to date."
    PORT=$(env_value ENCORE_PORT); PORT=${PORT:-4533}
    MUSIC_DIR=$(env_value ENCORE_MUSIC_DIR); MUSIC_DIR=${MUSIC_DIR:-/srv/music}
else
    [ -n "$SERVER_NAME" ] || SERVER_NAME="$(ask 'What should this server be called?' "$(hostname)'s music")"
    if [ -z "$OWNER" ]; then OWNER="$(ask 'Your username (3 to 32 letters, digits, . - _):' "")"; fi
    [ -n "$OWNER" ] || die "A username is needed for the owner's account (use --owner NAME)."
    if [ -z "$OWNER_PASSWORD" ]; then
        first="$(ask_secret 'Choose a password (8 or more characters):')" || die "A password is needed (set ENCORE_OWNER_PASSWORD when nobody can be asked)."
        second="$(ask_secret 'Type it again:')" || die "A password is needed."
        [ "$first" = "$second" ] || die "The two passwords are not the same. Run this again."
        OWNER_PASSWORD="$first"
    fi
    [ "${#OWNER_PASSWORD}" -ge 8 ] || die "The password is too short: use 8 or more characters."
    MUSIC_DIR="$(ask 'Where is your music? (a folder; it is only read)' "$MUSIC_DIR")"
    # The name goes into a settings file: leave out what that file treats as more than text.
    SERVER_NAME=${SERVER_NAME//[\$\"\`\'#\\]/}
    [ -n "$SERVER_NAME" ] || SERVER_NAME="My music server"
fi

mkdir -p "$MUSIC_DIR" || die "The music folder ${MUSIC_DIR} could not be made."
SONGS=$(find "$MUSIC_DIR" -type f \( -iname '*.mp3' -o -iname '*.flac' -o -iname '*.m4a' -o -iname '*.ogg' -o -iname '*.opus' -o -iname '*.wav' \) 2>/dev/null | wc -l)
ok "Your music: ${MUSIC_DIR} (${SONGS} songs found)"

# ---------------------------------------------------------------------------------------------------------------- Docker

if ! command -v docker >/dev/null 2>&1; then
    say ""
    if ask_yes "Docker is not installed. Encore needs it to run. Install it now?"; then
        say "  … Installing Docker (a minute or two)"
        log "installing Docker with get.docker.com"
        (curl -fsSL https://get.docker.com | sh) >>"$LOG" 2>&1 || die "Docker could not be installed. See the log; nothing else was changed."
    else
        die "Encore cannot run without Docker. Install it (https://docs.docker.com/engine/install/) and run this again."
    fi
fi
systemctl enable --now docker >>"$LOG" 2>&1 || true
docker info >>"$LOG" 2>&1 || die "Docker is installed but not running. Start it with  sudo systemctl start docker  and run this again."
if ! docker compose version >>"$LOG" 2>&1; then
    apt-get install -y -qq docker-compose-plugin >>"$LOG" 2>&1 || die "Docker is here but its 'compose' part is missing and could not be installed."
fi
ok "Docker is ready ($(docker --version | sed 's/Docker version //; s/,.*//'))"
log "docker ready after $(since) s"

# ---------------------------------------------------------------------------------------------------------------- the image

registry_login() { # a private image is pulled with a GitHub token that may read packages
    local token="${GH_TOKEN:-${GHCR_TOKEN:-}}" user=""
    if [ -z "$token" ] && command -v gh >/dev/null 2>&1; then
        token="$(gh auth token 2>/dev/null || true)"
        # Under sudo the sign-in belongs to the person who typed sudo, not to root (and newer sudo passes no environment variables on).
        if [ -z "$token" ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then token="$(sudo -u "$SUDO_USER" gh auth token 2>/dev/null || true)"; fi
    fi
    if [ -z "$token" ]; then
        say ""
        say "  This version of Encore is still private. Sign in with GitHub to download it:"
        token="$(ask_secret 'Paste a GitHub token that may read packages (or press Enter to stop):')" || token=""
    fi
    [ -n "$token" ] || die "The Encore image needs a GitHub sign-in. Run  gh auth login --scopes read:packages  and try again, or set GH_TOKEN."
    user="$(curl -fsS -m 15 -H "Authorization: Bearer $token" https://api.github.com/user 2>>"$LOG" | sed -n 's/.*"login": *"\([^"]*\)".*/\1/p' | head -1)"
    [ -n "$user" ] || die "GitHub did not accept that token."
    printf '%s' "$token" | docker login ghcr.io -u "$user" --password-stdin >>"$LOG" 2>&1 || die "Signing in to the image registry failed. The token needs the read:packages permission."
}

say ""
say "  … Downloading Encore (about 500 MB the first time)"
if ! docker pull "$IMAGE:$TAG" >>"$LOG" 2>&1; then
    log "pull failed, signing in"
    registry_login
    docker pull "$IMAGE:$TAG" >>"$LOG" 2>&1 || die "The Encore image ${IMAGE}:${TAG} could not be downloaded. See the log."
fi
ok "Encore downloaded"
log "images downloaded after $(since) s"

mkdir -p "$DIR/data" "$DIR/navidrome"
# The deployment files travel inside the image, so they always match the version that was downloaded.
docker run --rm --entrypoint cat "$IMAGE:$TAG" /app/deploy/compose.yaml >"$DIR/compose.yaml.new" 2>>"$LOG" || die "The image has no deployment files."
mv "$DIR/compose.yaml.new" "$DIR/compose.yaml"
docker run --rm --entrypoint cat "$IMAGE:$TAG" /app/deploy/encore >/usr/local/bin/encore.new 2>>"$LOG" || die "The image has no encore command."
chmod 755 /usr/local/bin/encore.new
mv /usr/local/bin/encore.new /usr/local/bin/encore

if [ "$FRESH" = 1 ]; then
    umask 077
    {
        echo "# Written by the Encore installer on $(date -u +%F). Keep this file private: it holds the music server's own password."
        echo "ENCORE_IMAGE=$IMAGE"
        echo "ENCORE_TAG=$TAG"
        echo "ENCORE_PORT=$PORT"
        echo "ENCORE_MUSIC_DIR=$MUSIC_DIR"
        echo "ENCORE_SERVER_NAME=$SERVER_NAME"
        echo "ENCORE_NAVIDROME_ADMIN_USER=encore-admin"
        echo "ENCORE_NAVIDROME_ADMIN_PASSWORD=$(head -c 32 /dev/urandom | base64 | tr -d '/+=\n' | cut -c1-32)"
    } >"$DIR/.env"
    chmod 600 "$DIR/.env"
    umask 022
fi

# ---------------------------------------------------------------------------------------------------------------- start

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "${PORT}/tcp" >>"$LOG" 2>&1 && note "The computer's firewall now lets Encore's port (${PORT}) in."
fi

dc() { docker compose --project-directory "$DIR" "$@"; }
say "  … Starting Encore"
dc up -d >>"$LOG" 2>&1 || die "Encore could not be started. See the log."

for _ in $(seq 1 90); do
    [ "$(curl -s -m 4 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/encore/api/v1/info" 2>/dev/null)" = 200 ] && break
    sleep 2
done
[ "$(curl -s -m 4 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/encore/api/v1/info" 2>/dev/null)" = 200 ] \
    || die "Encore started but did not answer in 3 minutes. Run  encore logs  to see why."
ok "Encore is running"
log "encore running after $(since) s"

if [ "$FRESH" = 1 ]; then
    # The owner's details go in on standard input from a file only this account can read, never on a command line.
    details="$(mktemp)"
    chmod 600 "$details"
    json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
    printf '{"username":"%s","password":"%s","name":"%s"}' "$(json_escape "$OWNER")" "$(json_escape "$OWNER_PASSWORD")" "$(json_escape "$OWNER")" >"$details"
    if ! dc exec -T encore-server python -m encore_server setup <"$details" >>"$LOG" 2>"$details.err"; then
        message="$(sed -n 's/^setup: //p' "$details.err" | head -1)"
        rm -f "$details" "$details.err"
        [ -n "$message" ] || message="Your account could not be made. See the log."
        die "$message"
    fi
    rm -f "$details" "$details.err"
    ok "Your account is made: ${OWNER}"
fi

# A copy of the accounts, playlists and likes every night (switched off for good by  encore autobackup off ), and one right now.
if [ "$(sed -n 's/^ENCORE_AUTOBACKUP=//p' "$DIR/.env" | head -1)" != 0 ]; then
    if /usr/local/bin/encore autobackup on >>"$LOG" 2>&1 && /usr/local/bin/encore backup --quiet >>"$LOG" 2>&1; then
        ok "A backup is made every night (the newest 7 are kept)"
    else
        note "The nightly backup could not be switched on; run  encore backup  yourself from time to time. See the log."
    fi
fi

# ---------------------------------------------------------------------------------------------------------------- done

HOST_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") {print $(i + 1); exit}}')"
[ -n "$HOST_IP" ] || HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
URL="http://${HOST_IP}:${PORT}"

say ""
say "  ${BOLD}Encore is ready.${OFF} In the Encore app on your phone (on the same Wi-Fi) sign in with:"
say ""
say "        Address:   ${HOST_IP}:${PORT}"
if [ "$FRESH" = 1 ]; then say "        Username:  ${OWNER}"; say "        Password:  the one you just chose"; fi
say ""
if command -v qrencode >/dev/null 2>&1 || { apt-get install -y -qq qrencode >>"$LOG" 2>&1 && command -v qrencode >/dev/null 2>&1; }; then
    qrencode -t ANSIUTF8 -m 2 "$URL" 2>>"$LOG" | sed 's/^/        /' || true
    say ""
fi
say "  To use it away from home, then invite friends:   encore funnel on"
say "  To see how it is doing, update or remove it:       encore status | encore update | encore uninstall"
say ""
note "Installed in $(($(since) / 60)) min $(($(since) % 60)) s (the time you spent answering is in it)."
log "=== done after $(since) s"
