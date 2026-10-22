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
    exec setpriv --reuid=1000 --regid=1000 --init-groups "$@"
fi
exec "$@"
