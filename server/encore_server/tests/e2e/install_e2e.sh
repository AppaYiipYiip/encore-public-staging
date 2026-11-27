#!/usr/bin/env bash
# The REAL install, end to end, once per door (P3-06; the lesson of 27 Nov 2026).
#
# Two defects of the first run in the browser were invisible to every stub test and found only by a reviewer reading the install sequence: a music server left with no account (its
# first-account address open to the home network) and a keys step that signed in with an account nobody had made. This runs `install.sh` itself, on a clean machine, against an image
# built from this very change, and then walks the first run the way a Host does. Nothing here is a stand-in: real Docker, the real music server, the real installer, the real `encore`.
#
#   sudo bash install_e2e.sh browser|headless IMAGE TAG
#
# IMAGE:TAG is pulled by the installer exactly as a stranger's would be (CI puts this change's image in a local registry on localhost:5000; the product has no test-only flag).
# The machine is a throwaway: the setup code, the backup key and the recovery keys that this prints are worth nothing. It is engineering proof of the install sequence, NOT a "walked"
# row: P3-07's walk of both doors on a clean machine, by hand, is still owed.
set -Eeuo pipefail

DOOR="${1:?browser or headless}"
IMAGE="${2:?the image, without its tag}"
TAG="${3:?the tag}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$HERE/../../deploy"
DIR=/opt/encore
PORT=4533
BASE="http://127.0.0.1:${PORT}"
API="$BASE/encore/api/v1"
WORK="$(mktemp -d)"
PASSWORD="correct horse battery"
NEW_PASSWORD="another long password"
OWNER=riley

dump() {
    echo "----- the last of /var/log/encore-install.log"
    tail -n 60 /var/log/encore-install.log 2>/dev/null || true
    echo "----- the containers"
    docker ps -a 2>/dev/null || true
    if [ -f "$DIR/compose.yaml" ]; then docker compose --project-directory "$DIR" logs --tail 60 2>/dev/null || true; fi
    echo "----- the names (never the values) in .env"
    sed 's/=.*/=.../' "$DIR/.env" 2>/dev/null || true
}
fail() {
    echo "::error::E2E FAILED ($DOOR door): $*"
    dump
    exit 1
}
trap 'fail "the script stopped at line $LINENO"' ERR

step() { printf '\n=== %s\n' "$*"; }
ok() { printf '  ok: %s\n' "$*"; }
expect() { # expect "what" ACTUAL EXPECTED
    [ "$2" = "$3" ] || fail "$1: expected [$3], got [$2]"
    ok "$1"
}
expect_match() { # expect_match "what" ACTUAL REGEX
    printf '%s' "$2" | grep -Eq -- "$3" || fail "$1: [$2] does not match $3"
    ok "$1"
}
status_of() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
login() { # login USER PASSWORD -> the answer's body
    curl -s -X POST "$API/auth/login" -H 'Content-Type: application/json' \
        -d "$(jq -nc --arg u "$1" --arg p "$2" '{username:$u,password:$p,deviceName:"ci",deviceKind:"phone"}')"
}
me_status() { status_of "$API/me" -H "Authorization: Bearer $1"; }
env_has() { grep -Eq "^$1=" "$DIR/.env"; }

[ "$(id -u)" = 0 ] || fail "run this as root (sudo)"

# ------------------------------------------------------------------------------------------------------------------------------------ the install
step "install.sh, ${DOOR} door"
printf '%s\n' "$PASSWORD" >"$WORK/pw"
chmod 600 "$WORK/pw"
mkdir -p /srv/music
if [ "$DOOR" = browser ]; then
    bash "$DEPLOY/install.sh" --yes --image "$IMAGE" --tag "$TAG" --name "CI music" --music-dir /srv/music >"$WORK/install.out" 2>&1 || { cat "$WORK/install.out"; fail "install.sh did not finish"; }
else
    bash "$DEPLOY/install.sh" --yes --image "$IMAGE" --tag "$TAG" --name "CI music" --music-dir /srv/music --owner "$OWNER" --owner-password-file "$WORK/pw" >"$WORK/install.out" 2>&1 \
        || { cat "$WORK/install.out"; fail "install.sh did not finish"; }
fi
cat "$WORK/install.out"
ok "install.sh finished"
expect "the server answers" "$(status_of "$API/info")" 200

step "the music server's first-account address is closed to everybody (the takeover the review found)"
expect "POST /auth/createAdmin is refused" "$(status_of -X POST "$BASE/auth/createAdmin" -H 'Content-Type: application/json' -d '{"username":"mallory","password":"x-x-x-x-x-x-x-x"}')" 404
expect "and in another spelling" "$(status_of -X POST "$BASE//auth/createAdmin/" -H 'Content-Type: application/json' -d '{"username":"mallory","password":"x-x-x-x-x-x-x-x"}')" 404
step "the keys of the install were made (the step that signs in with the music server's own account)"
[ -f "$DIR/backup.pub" ] || fail "no backup.pub: the keys step did not run"
ok "the backup key's public half is there"
expect_match "the output tells the Host where the backup key is" "$(cat "$WORK/install.out")" "Your backup key"

# ------------------------------------------------------------------------------------------------------------------------------------ the owner
if [ "$DOOR" = browser ]; then
    step "the browser door: the link, the code, the page, the owner"
    CODE="$(sed -n 's#.*/setup?code=\([2-9A-HJ-KM-NP-Z]\{3\}-[2-9A-HJ-KM-NP-Z]\{3\}\).*#\1#p' "$WORK/install.out" | head -1)"
    [ -n "$CODE" ] || fail "the installer showed no setup link"
    env_has ENCORE_SETUP_CODE || fail "the setup code is not in .env"
    expect "the code shown is the code in .env" "$(sed -n 's/^ENCORE_SETUP_CODE=//p' "$DIR/.env")" "$CODE"
    ok "the installer showed the link and the code"
    [ "$(stat -c %a "$DIR/.env")" = 600 ] || fail ".env is not private"
    expect "the page opens" "$(status_of "$BASE/encore/setup")" 200
    expect "the short address redirects" "$(status_of "$BASE/setup?code=$CODE")" 302
    expect "state without the code is refused" "$(status_of "$API/setup/state")" 403
    expect "state with the code" "$(status_of "$API/setup/state" -H "X-Setup-Code: $CODE")" 200
    OWNER_ANSWER="$(curl -s -X POST "$API/setup/owner" -H "X-Setup-Code: $CODE" -H 'Content-Type: application/json' \
        -d "$(jq -nc --arg u "$OWNER" --arg p "$PASSWORD" '{username:$u,password:$p,name:"Riley"}')")"
    TOKEN="$(printf '%s' "$OWNER_ANSWER" | jq -r '.deviceToken // empty')"
    KEY1="$(printf '%s' "$OWNER_ANSWER" | jq -r '.recoveryKey // empty')"
    [ -n "$TOKEN" ] || fail "the owner was not made: $OWNER_ANSWER"
    expect_match "a recovery key was shown" "$KEY1" '^[2-9A-HJ-KM-NP-Z]{4}(-[2-9A-HJ-KM-NP-Z]{4}){4}$'
    expect "the browser session works" "$(me_status "$TOKEN")" 200
    expect "the first run is closed for ever" "$(status_of "$API/setup/state" -H "X-Setup-Code: $CODE")" 404
    expect "and the page sends the Host to sign in" "$(status_of "$BASE/encore/setup")" 302
    step "the encore command tidies the setup code"
    STATUS_OUT="$(encore status 2>&1)" || fail "encore status failed: $STATUS_OUT"
    printf '%s\n' "$STATUS_OUT"
    if env_has ENCORE_SETUP_CODE; then fail "the setup code is still in .env"; fi
    ok "the code left .env"
    if printf '%s' "$STATUS_OUT" | grep -q "setup?code"; then fail "encore status still shows the setup link"; fi
    ok "encore status shows no link"
else
    step "the headless door: no setup page, the owner signs in"
    if env_has ENCORE_SETUP_CODE; then fail "a setup code was made for an install that has its owner"; fi
    ok "no setup code"
    expect "the first-run routes do not exist" "$(status_of "$API/setup/state")" 404
    expect "the setup page sends the Host to sign in" "$(status_of "$BASE/encore/setup")" 302
    KEY1=""
fi

step "the owner signs in with the password they chose (the real music server's login)"
SIGN_IN="$(login "$OWNER" "$PASSWORD")"
expect "the owner's role" "$(printf '%s' "$SIGN_IN" | jq -r '.person.role // empty')" owner
TOKEN="$(printf '%s' "$SIGN_IN" | jq -r '.deviceToken')"
expect "a wrong password is refused" "$(status_of -X POST "$API/auth/login" -H 'Content-Type: application/json' -d '{"username":"riley","password":"not the password"}')" 401

# ------------------------------------------------------------------------------------------------------------------------------------ the way back
step "encore reset-password (the first real run of the music server's password change through the command door)"
printf '%s\n' "$NEW_PASSWORD" >"$WORK/pw2"
chmod 600 "$WORK/pw2"
if [ "$DOOR" = browser ]; then
    printf '%s\n' "$KEY1" >"$WORK/key1"
    chmod 600 "$WORK/key1"
    RESET_OUT="$(encore reset-password "$OWNER" --password-file "$WORK/pw2" --recovery-key-file "$WORK/key1" 2>&1)" || fail "reset-password failed: $RESET_OUT"
else
    RESET_OUT="$(encore reset-password "$OWNER" --password-file "$WORK/pw2" 2>&1)" || fail "reset-password failed: $RESET_OUT"
fi
printf '%s\n' "$RESET_OUT"
expect_match "the password is changed" "$RESET_OUT" "The password of ${OWNER} is changed"
KEY2="$(printf '%s\n' "$RESET_OUT" | grep -Eo '[2-9A-HJ-KM-NP-Z]{4}(-[2-9A-HJ-KM-NP-Z]{4}){4}' | head -1)"
[ -n "$KEY2" ] || fail "no new recovery key was shown"
if [ -n "$KEY1" ] && [ "$KEY1" = "$KEY2" ]; then fail "the recovery key was not replaced"; fi
ok "a new recovery key was shown"
expect "the old browser session is refused" "$(me_status "$TOKEN")" 401
expect "the old password no longer signs in" "$(status_of -X POST "$API/auth/login" -H 'Content-Type: application/json' -d "$(jq -nc --arg p "$PASSWORD" '{username:"riley",password:$p}')")" 401
SIGN_IN="$(login "$OWNER" "$NEW_PASSWORD")"
expect "the new password signs in" "$(printf '%s' "$SIGN_IN" | jq -r '.person.role // empty')" owner
TOKEN="$(printf '%s' "$SIGN_IN" | jq -r '.deviceToken')"
if [ "$DOOR" = browser ]; then
    step "the spent key is refused"
    if encore reset-password "$OWNER" --password-file "$WORK/pw2" --recovery-key-file "$WORK/key1" >"$WORK/spent.out" 2>&1; then fail "a spent recovery key was accepted"; fi
    expect_match "in words" "$(cat "$WORK/spent.out")" "recovery key is not right"
fi
step "encore recovery-key"
KEY_OUT="$(encore recovery-key 2>&1)" || fail "recovery-key failed: $KEY_OUT"
expect_match "a new key is shown" "$KEY_OUT" '[2-9A-HJ-KM-NP-Z]{4}(-[2-9A-HJ-KM-NP-Z]{4}){4}'
step "an unknown person is told in words"
if encore reset-password nobody-here --password-file "$WORK/pw2" >"$WORK/nobody.out" 2>&1; then fail "a reset of nobody succeeded"; fi
expect_match "in words" "$(cat "$WORK/nobody.out")" "nobody called"

# ------------------------------------------------------------------------------------------------------------------------------------ what the computer tells the server
step "a backup, and what Home says about it"
encore backup --quiet >"$WORK/backup.out" 2>&1 || { cat "$WORK/backup.out"; fail "encore backup failed"; }
[ -f "$DIR/data/host-status.json" ] || fail "no host-status.json after a backup"
jq -e '.lastBackup.at and .lastBackup.locked == true' "$DIR/data/host-status.json" >/dev/null || fail "host-status.json does not tell of a locked backup: $(cat "$DIR/data/host-status.json")"
ok "the computer told the server about the backup"
HEALTH="$(curl -s "$API/admin/health" -H "Authorization: Bearer $TOKEN")"
expect "the backup row says ok" "$(printf '%s' "$HEALTH" | jq -r '.rows[] | select(.id == "backup") | .state')" ok
expect "the music server row says working" "$(printf '%s' "$HEALTH" | jq -r '.rows[] | select(.id == "music-server") | .state')" ok
step "encore addon list (the command door into the running server)"
ADDONS="$(encore addon list 2>&1)" || fail "encore addon list failed: $ADDONS"
expect_match "the add-ons are listed" "$ADDONS" "youtube"
step "the audit log holds the acts, and no secret"
AUDIT="$(docker compose --project-directory "$DIR" exec -T encore-server python -c "import sqlite3; print(chr(10).join(r[0] for r in sqlite3.connect('/data/encore.db').execute('select detail from audit_log')))")"
printf '%s\n' "$AUDIT"
expect_match "the reset is in the audit log" "$AUDIT" "was reset at the server computer"
for secret in "$PASSWORD" "$NEW_PASSWORD" "$KEY2"; do
    if printf '%s' "$AUDIT" | grep -qF -- "$secret"; then fail "a secret is in the audit log"; fi
done
ok "no secret in the audit log"

step "ALL GOOD ($DOOR door)"
