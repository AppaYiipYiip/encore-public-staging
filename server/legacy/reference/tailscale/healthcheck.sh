#!/bin/sh
# Health check of the Funnel sidecar (docs/33 section 6, cost 4b; proved by tests/check_reference.py).
#
# Healthy  = connected to Tailscale AND the machine's key does not end within WARN_DAYS.
# Unhealthy prints why, so `docker compose ps` shows "unhealthy" and
#   docker inspect --format '{{json .State.Health}}' encore-tailscale
# shows the sentence. A Tailscale key lasts 180 days by default; when it ends, remote access stops without a sound.
# The fix is one click in the Tailscale admin console ("Disable key expiry" for this machine), see the guide.
#
# TS_STATUS_FILE and TS_HEALTH_URL exist so the test can feed it fake situations; in the container neither is set.

WARN_DAYS="${WARN_DAYS:-14}"
URL="${TS_HEALTH_URL:-http://127.0.0.1:9002/healthz}"

if ! wget -q --spider -T 4 "$URL" 2>/dev/null; then
  echo "not connected to Tailscale (yet): open the sign-in link in 'docker compose logs tailscale', or check the machine's internet"
  exit 1
fi

if [ -n "${TS_STATUS_FILE:-}" ]; then
  json=$(cat "$TS_STATUS_FILE")
else
  # Self only: with peers the first KeyExpiry could belong to another machine.
  json=$(tailscale --socket=/tmp/tailscaled.sock status --peers=false --json 2>/dev/null)
fi

# "KeyExpiry":"2027-04-07T19:56:54Z" - absent, null or the zero time when expiry is switched off.
expiry=$(printf '%s' "$json" | tr -d '\n' | sed -n 's/.*"KeyExpiry": *"\([0-9][0-9-]*T[0-9:]*\)Z".*/\1/p')
[ -z "$expiry" ] && exit 0

when=$(date -u -d "$(printf '%s' "$expiry" | sed 's/T/ /')" +%s 2>/dev/null) || exit 0
[ "$when" -lt 946684800 ] && exit 0            # before the year 2000: the zero time, i.e. never

now=$(date -u +%s)
left=$(( (when - now + 86399) / 86400 ))        # whole days, rounded up: "5 days" never reads "4"
if [ "$when" -le "$now" ]; then
  echo "the key of this machine has expired: remote access is off. Sign in again (docker compose logs tailscale) and switch key expiry off in the Tailscale admin console"
  exit 1
fi
if [ $(( when - now )) -lt $(( WARN_DAYS * 86400 )) ]; then
  echo "remote access stops in $left day(s): the key of this machine expires. Switch key expiry off for it in the Tailscale admin console (Machines > the machine's menu > Disable key expiry)"
  exit 1
fi
exit 0
