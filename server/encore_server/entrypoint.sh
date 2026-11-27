#!/bin/sh
# Starts as root only to make the data folder writable, then runs the server as an ordinary user (uid 1000).
# A folder the person made (or Docker made for them) is often owned by root; a server that then cannot open its database and
# restarts forever is the worst first minute, so the fix is here and not in the install guide.
set -e

if [ "$(id -u)" = "0" ]; then
    if [ "$(stat -c %u /data)" != "1000" ]; then
        chown -R 1000:1000 /data
    fi
    # The folder the server keeps songs in, inside the music folder (never the whole library: that is the person's).
    if [ -d /music ] && [ ! -e /music/Encore ]; then
        mkdir -p /music/Encore 2>/dev/null || true
    fi
    if [ -d /music/Encore ] && [ "$(stat -c %u /music/Encore)" != "1000" ]; then
        chown 1000:1000 /music/Encore 2>/dev/null || true
    fi
    # The server keeps ONE supplementary group, the helper's (docs/36 section 3: the socket is root:encore-helper, mode 660), when the install has a helper; none otherwise. `--init-groups` would
    # drop the group the compose file gave this container, and `--keep-groups` would keep root's own group 0 as well: the id is named, and it must be a number.
    case "${ENCORE_HELPER_GID:-}" in
        "") exec setpriv --reuid=1000 --regid=1000 --clear-groups "$@" ;;
        *[!0-9]*) echo "entrypoint: ENCORE_HELPER_GID is not a number: the helper's group is not used" >&2; exec setpriv --reuid=1000 --regid=1000 --clear-groups "$@" ;;
        *) exec setpriv --reuid=1000 --regid=1000 --groups="$ENCORE_HELPER_GID" "$@" ;;
    esac
fi
exec "$@"
