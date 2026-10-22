#!/bin/sh
# Starts as root only to make the data folder writable, then runs the server as an ordinary user (uid 1000).
# A folder the person made (or Docker made for them) is often owned by root; a server that then cannot open its database and
# restarts forever is the worst first minute, so the fix is here and not in the install guide.
set -e

if [ "$(id -u)" = "0" ]; then
    if [ "$(stat -c %u /data)" != "1000" ]; then
        chown -R 1000:1000 /data
    fi
    exec setpriv --reuid=1000 --regid=1000 --init-groups "$@"
fi
exec "$@"
