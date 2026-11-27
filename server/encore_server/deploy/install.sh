#!/usr/bin/env bash
# Encore installer (docs/tasks P3-05): installs the music server and the Encore server on this computer.
#
#   sudo bash install.sh                     asks what it needs (where the music is); your account is made afterwards, in the browser, with a setup code this screen shows
#   sudo bash install.sh --yes --owner NAME  asks nothing it can do without and makes the account itself (an install nobody sits at); the password comes from ENCORE_OWNER_PASSWORD
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

# Writing to a terminal that has gone away (the window was closed, the connection dropped) must not end an install that is already
# running: after the questions are answered nothing needs the terminal, so every message is allowed to fail.
say() { printf '%s\n' "$*" || true; }
ok() { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$*" || true; }
note() { printf '  %s%s%s\n' "$DIM" "$*" "$OFF" || true; }
die() {
    printf '\n  %s✗ %s%s\n' "$RED" "$*" "$OFF" >&2 || true
    printf '  %sThe details are in %s. Running the same command again is safe.%s\n\n' "$DIM" "$LOG" "$OFF" >&2 || true
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
  --owner NAME           make the owner's account here, with this username (3 to 32 letters, digits, . - _), instead of in the browser (for installs nobody sits at)
  --owner-password-file F  read the owner's password from the first line of file F
  --name TEXT            the server's name, shown to people you invite (default: this computer's name)
  --music-dir PATH       where the music is, or will be (default /srv/music)
  --port N               the port the apps connect to (default 4533)
  --dir PATH             where Encore keeps its files (default /opt/encore)
  --image NAME           the server image (default ghcr.io/appayiipyiip/encore-server)
  --tag TAG              the image version (default main)

Without --owner, the account is made on a page you open afterwards (the link and a setup code are shown at the end). With --owner, the password is asked for, or read from a file (--owner-password-file), or from ENCORE_OWNER_PASSWORD. For a private image, sign in to
GitHub first with  gh auth login --scopes read:packages  (the installer finds that login even under sudo), or give a token that may read
packages in GH_TOKEN / GHCR_TOKEN.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --yes | -y) YES=1 ;;
        --owner) OWNER="${2:?--owner needs a name}"; shift ;;
        --owner-password-file)
            [ -r "${2:?--owner-password-file needs a file}" ] || die "The password file $2 cannot be read."
            OWNER_PASSWORD="$(head -n 1 "$2")"; shift ;;
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
# The first install writes this before its settings file and removes it once the owner's account exists: if the install was cut short in
# between (power, Ctrl-C, a dropped connection), running the installer again finishes the job instead of leaving a server nobody can sign in to.
PENDING=0
[ -f "$DIR/.setup-pending" ] && PENDING=1
# Who makes the owner's account (docs/36 section 2, "The first run is a takeover risk"). By default the person does, in the browser, with a setup code that only the
# screen of this computer shows: nothing is asked here. `--owner NAME` is the other door (an install nobody sits at, a test rig): the installer makes the account as it
# always did, and there is then no setup page.
NEED_OWNER=0
BROWSER_OWNER=0
if [ "$FRESH" = 1 ] || [ "$PENDING" = 1 ]; then
    if [ -n "$OWNER" ]; then NEED_OWNER=1; else BROWSER_OWNER=1; fi
fi

env_value() { grep -E "^$1=" "$DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- || true; }

# The setup code: six characters of the 31 that cannot be mistaken for each other (no 0 O 1 I L), shown as 7KQ-4MZ. `tr` is closed by `head` and says so: that is not a failure.
make_setup_code() {
    local raw
    raw="$(LC_ALL=C tr -dc '23456789ABCDEFGHJKMNPQRSTUVWXYZ' </dev/urandom | head -c 6 || true)"
    [ "${#raw}" = 6 ] || return 1
    printf '%s-%s' "${raw:0:3}" "${raw:3:3}"
}

# Makes sure the settings file has a setup code (once: a second run keeps the one that is there, so a link already shown still works).
ensure_setup_code() {
    local code
    [ -n "$(env_value ENCORE_SETUP_CODE)" ] && return 0
    code="$(make_setup_code)" || die "A setup code could not be made."
    {
        echo "# Only until the owner's account is made in the browser: the setup pages need it, the encore command takes it out afterwards."
        echo "ENCORE_SETUP_CODE=$code"
    } >>"$DIR/.env"
}
host_ip() {
    local ip
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") {print $(i + 1); exit}}')"
    [ -n "$ip" ] || ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    printf '%s' "$ip"
}

ask_owner() { # the owner's username and password, from the options or by asking
    if [ -z "$OWNER" ]; then OWNER="$(ask 'Your username (3 to 32 letters, digits, . - _):' "")"; fi
    [ -n "$OWNER" ] || die "A username is needed for the owner's account (use --owner NAME)."
    if [ -z "$OWNER_PASSWORD" ]; then
        first="$(ask_secret 'Choose a password (8 or more characters):')" || die "A password is needed (set ENCORE_OWNER_PASSWORD when nobody can be asked)."
        second="$(ask_secret 'Type it again:')" || die "A password is needed."
        [ "$first" = "$second" ] || die "The two passwords are not the same. Run this again."
        OWNER_PASSWORD="$first"
    fi
    [ "${#OWNER_PASSWORD}" -ge 8 ] || die "The password is too short: use 8 or more characters."
}

if [ "$FRESH" = 0 ]; then
    PORT=$(env_value ENCORE_PORT); PORT=${PORT:-4533}
    MUSIC_DIR=$(env_value ENCORE_MUSIC_DIR); MUSIC_DIR=${MUSIC_DIR:-/srv/music}
    if [ "$PENDING" = 1 ] && [ "$NEED_OWNER" = 1 ]; then
        note "An earlier install here was cut short before your account was made: finishing it."
        say "  Choose the username and password for your account now. If you already chose them the first time, type the same ones."
        ask_owner
    elif [ "$PENDING" = 1 ]; then
        note "An earlier install here was cut short before your account was made: you make it in the browser, at the end of this."
    else
        note "Encore is already installed here: it is kept and brought up to date."
    fi
else
    [ -n "$SERVER_NAME" ] || SERVER_NAME="$(ask 'What should this server be called?' "$(hostname)'s music")"
    if [ "$NEED_OWNER" = 1 ]; then ask_owner; fi
    MUSIC_DIR="$(ask 'Where is your music? (a folder; Encore never changes your files)' "$MUSIC_DIR")"
    # The name goes into a settings file: leave out what that file treats as more than text.
    SERVER_NAME=${SERVER_NAME//[\$\"\`\'#\\]/}
    [ -n "$SERVER_NAME" ] || SERVER_NAME="My music server"
fi

# From here nothing needs the terminal: a window that is closed, or a connection that drops, must not stop an install half way.
trap '' HUP

mkdir -p "$MUSIC_DIR" || die "The music folder ${MUSIC_DIR} could not be made."
SONGS=$(find "$MUSIC_DIR" -type f \( -iname '*.mp3' -o -iname '*.flac' -o -iname '*.m4a' -o -iname '*.ogg' -o -iname '*.opus' -o -iname '*.wav' \) 2>/dev/null | wc -l)
ok "Your music: ${MUSIC_DIR} (${SONGS} songs found)"
note "Songs you keep from the web are saved in a folder called Encore inside it; nothing else in it is changed."

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
say "  … Downloading Encore (about 240 MB the first time)"
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
    # The music server's data of an earlier install, locked with a key whose settings file is gone: a new key would lock everybody out for good (P3-30).
    if [ -f "$DIR/navidrome/.encore-password-key.sha256" ]; then
        die "$DIR/navidrome holds the accounts of an earlier install, locked with a key that was in the settings file ($DIR/.env) that is gone. Putting a new key here would lock everybody out for good. Restore the settings file from a backup (encore restore reads it), or move that folder away to start empty."
    fi
    umask 077
    if [ "$NEED_OWNER" = 1 ]; then : >"$DIR/.setup-pending"; fi
    {
        echo "# Written by the Encore installer on $(date -u +%F). Keep this file private: it holds the music server's own password."
        echo "ENCORE_IMAGE=$IMAGE"
        echo "ENCORE_TAG=$TAG"
        echo "ENCORE_PORT=$PORT"
        echo "ENCORE_MUSIC_DIR=$MUSIC_DIR"
        echo "ENCORE_SERVER_NAME=$SERVER_NAME"
        echo "ENCORE_NAVIDROME_ADMIN_USER=encore-admin"
        echo "ENCORE_NAVIDROME_ADMIN_PASSWORD=$(head -c 32 /dev/urandom | base64 | tr -d '/+=\n' | cut -c1-32)"
        echo "# The key every person's password is stored under in the music server. Never change it, never lose it (it is in every backup)."
        echo "ENCORE_PASSWORD_KEY=$(head -c 96 /dev/urandom | base64 -w0 | tr -d '/+=\n' | cut -c1-48)"
    } >"$DIR/.env"
    chmod 600 "$DIR/.env"
    umask 022
fi
# An earlier install that was cut short before an account was made, finished in the browser now: the old marker is no longer true, the setup code is what opens the pages.
if [ "$BROWSER_OWNER" = 1 ]; then
    rm -f "$DIR/.setup-pending"
    ensure_setup_code
fi

# The address phones are told for this computer on the home network (the server hands it to signed-in phones: docs/11 ADR-R40). Kept up to date on every run.
HOST_IP="$(host_ip)"
if [ -n "$HOST_IP" ]; then
    if grep -q '^ENCORE_HOME_URL=' "$DIR/.env"; then
        sed -i "s|^ENCORE_HOME_URL=.*|ENCORE_HOME_URL=http://${HOST_IP}:${PORT}|" "$DIR/.env"
    else
        echo "ENCORE_HOME_URL=http://${HOST_IP}:${PORT}" >>"$DIR/.env"
    fi
fi

# ---------------------------------------------------------------------------------------------------------------- start

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "${PORT}/tcp" >>"$LOG" 2>&1 && note "The computer's firewall now lets Encore's port (${PORT}) in."
fi

dc() { docker compose --project-directory "$DIR" "$@"; }
# An earlier install whose accounts were locked with a key: never start the music server under another one (every sign-in would fail until the right key is back).
if [ -f "$DIR/navidrome/.encore-password-key.sha256" ]; then
    mark="$(head -1 "$DIR/navidrome/.encore-password-key.sha256")"
    key="$(env_value ENCORE_PASSWORD_KEY)"
    if [ -z "$key" ] || [ "$(printf '%s' "$key" | sha256sum | cut -d' ' -f1)" != "$mark" ]; then
        die "The accounts of this install are locked with a key that is missing from $DIR/.env or has been changed. Put the original line ENCORE_PASSWORD_KEY=... back (the settings file inside a backup has it; encore restore puts it back) before starting anything."
    fi
fi
# The music server's own image is the second download (about as big as the first on a slow line): say so, rather than looking stuck in "Starting".
say "  … Downloading the music server (about 95 MB the first time)"
dc pull navidrome >>"$LOG" 2>&1 || die "The music server could not be downloaded. See the log."
ok "Music server downloaded"
log "music server downloaded after $(since) s"
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

# The music server's own account for Encore, in EVERY install and on every run, whichever door makes the owner and before anything else can reach the music server: a music server
# with no account at all hands its first one to whoever asks (its /auth/createAdmin; the gateway refuses that address as well, but the account must exist). Safe to repeat: an
# account that already signs in is left as it is. On a first install it is fatal, because the keys step below signs in with it; on a re-run of a working install it is a warning.
admin_error="$(mktemp)"
if dc exec -T encore-server python -m encore_server setup --administrator-only >>"$LOG" 2>"$admin_error"; then
    rm -f "$admin_error"
else
    message="$(sed -n 's/^setup: //p' "$admin_error" | head -1)"
    rm -f "$admin_error"
    [ -n "$message" ] || message="The music server's account for Encore could not be made. See the log."
    if [ "$FRESH" = 1 ] || [ "$PENDING" = 1 ] || [ "$BROWSER_OWNER" = 1 ]; then die "$message"; fi
    note "$message"
fi

if [ "$NEED_OWNER" = 1 ]; then
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
    rm -f "$DIR/.setup-pending"
    ok "Your account is made: ${OWNER}"
fi

# The keys of this install (P3-30): the music server's passwords are locked with the key made above (proved now that the start worked), and the backups are locked
# to a public key whose secret half is shown ONCE, here, and kept nowhere on this computer. It is shown before the first backup is made, so every backup is locked.
# Its output is NOT redirected to the log: the secret half goes to this screen only.
if ! /usr/local/bin/encore secure --installer; then
    die "The keys of this install could not be made. Run  sudo encore secure  to try again."
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

HOST_IP="$(host_ip)"

# The browser door: the account is made on a page, with the code only this screen shows (a re-run of the installer shows the same link again until it is done).
SETUP_CODE="$(env_value ENCORE_SETUP_CODE)"
SETUP_PENDING=0
if [ -n "$SETUP_CODE" ] && [ ! -e "$DIR/data/setup-complete" ]; then SETUP_PENDING=1; fi

say ""
if [ "$SETUP_PENDING" = 1 ]; then
    say "  ${BOLD}Encore is installed. One step is left: make your account.${OFF} Open this link in a browser on this network (a computer or a phone):"
    say ""
    say "        http://${HOST_IP}:${PORT}/setup?code=${SETUP_CODE}"
    say ""
    say "  If the link does not open, go to  http://${HOST_IP}:${PORT}/setup  and type this setup code:  ${BOLD}${SETUP_CODE}${OFF}"
    say "  The code is only for this step: it stops anybody else on your network from claiming the server before you. It stops working once your account exists."
    say ""
    say "  Then, in the Encore app on your phone (on the same Wi-Fi), tap Connect and sign in with the account you made. Address:  ${HOST_IP}:${PORT}"
else
    say "  ${BOLD}Encore is ready.${OFF} In the Encore app on your phone (on the same Wi-Fi), tap Connect and sign in with:"
    say ""
    say "        Address:   ${HOST_IP}:${PORT}"
    if [ "$NEED_OWNER" = 1 ]; then say "        Username:  ${OWNER}"; say "        Password:  the one you just chose"; fi
fi
say ""
# No QR code here: it used to encode the bare address, which a phone's camera opens in the browser as the music server's own page, not Encore,
# and the app cannot scan it. A QR that carries an Encore setup link comes with the pairing link (docs/tasks AUDIT F16, P2-19 slice B).
say "  Please do not open that address in a browser: it shows the music server's own page, not Encore."
say "  The pages that look after the server are on your home network, in a browser on this network:"
say ""
say "        http://${HOST_IP}:${PORT}/admin      sign in with the owner account (Home and People are there; the rest is being built)"
say ""
say "  The same things are commands on this computer:"
say ""
say "        encore status             is it running, at which address, which version"
say "        encore logs               what it is saying (Ctrl-C to stop)"
say "        encore update             a backup first, then the newest version"
say "        encore backup | restore   a locked copy of the accounts, playlists and likes; put one back (restore asks for the backup key)"
say "        encore secure --check     is the backup key you saved the right one"
say "        encore start | stop       switch it on or off"
say "        encore uninstall          remove it (your music is never touched)"
say ""
say "  ${BOLD}Your backup key${OFF} was shown above, once. Encore does not keep it: without it a backup cannot be opened. Check you have it:  sudo encore secure --check"
say ""
say "  ${BOLD}Away from home (optional):${OFF}   encore funnel on"
say "  Lets your phone, and friends you invite, reach Encore from anywhere. It needs a free Tailscale"
say "  account: the command shows a link, you sign in there in a browser, and it prints an https"
say "  address. You can skip this and use Encore at home."
say ""
note "Installed in $(($(since) / 60)) min $(($(since) % 60)) s (the time you spent answering is in it)."
log "=== done after $(since) s"
