#!/bin/sh
# Keep yt-dlp current (best effort: a failed update must not stop the
# service), then run it.
mkdir -p "$HOME" /work

# A signed-in YouTube account needs a JavaScript runtime (Deno, installed in the image) to solve the player's puzzles; say so in the
# log if it is missing, because fetching as an account then fails (docs/50: found with the first real account).
command -v deno >/dev/null 2>&1 \
  || echo "WARNING: no JavaScript runtime (deno) in this image: fetching as a signed-in YouTube account will fail."

version() {
  pip show yt-dlp 2>/dev/null | sed -n 's/^Version: //p'
}

update() {
  # "[default]" keeps yt-dlp-ejs (the solver scripts) in step with yt-dlp itself.
  pip install --quiet --user --upgrade "yt-dlp[default]" mutagen ytmusicapi 2>/dev/null \
    || echo "yt-dlp update skipped (offline?); using the version already here"
}

update

# YouTube changes often, and a service that stays up for weeks would keep the version it started with. Look again every day.
# The service now runs yt-dlp inside its own process (the lean path), so a newer version is only loaded by a restart: when the
# version changed, stop the service and let the container's restart policy bring it back (a second or two). The loop ends with
# the service (it asks whether that process, which this shell turns into, is there).
main=$$
(
  while sleep "${YTDLP_UPDATE_EVERY:-86400}" && kill -0 "$main" 2>/dev/null; do
    before=$(version)
    update
    after=$(version)
    if [ -n "$before" ] && [ "$before" != "$after" ]; then
      echo "yt-dlp changed ($before -> $after): restarting the service to load it"
      kill -TERM "$main"
      exit 0
    fi
  done
) &

exec python -m encore_fetch
