#!/usr/bin/env bash
# On the dev VM: call the quality service as the owner or as the guest, the way the app would.  q.sh owner|guest METHOD PATH [json]
# The logins come from ~/encore-creds.txt; nothing secret is printed.
set -euo pipefail
. ~/encore-creds.txt
who="$1"; method="$2"; path="$3"; body="${4:-}"
if [[ $who == owner ]]; then user="$OWNER"; pw="$OWNER_PW"; else user="$GUEST"; pw="$GUEST_PW"; fi
IP=$(docker inspect -f '{{(index .NetworkSettings.Networks "encore-server_default").IPAddress}}' encore-quality)
salt=$(openssl rand -hex 6); tok=$(printf '%s%s' "$pw" "$salt" | md5sum | cut -d' ' -f1)
sep='?'; [[ $path == *\?* ]] && sep='&'
if [[ -n $body ]]; then
  curl -s -m 120 -X "$method" "http://$IP:8704${path}${sep}u=$user&t=$tok&s=$salt" -H 'Content-Type: application/json' -d "$body" -w '\n[%{http_code}]\n'
else
  curl -s -m 120 -X "$method" "http://$IP:8704${path}${sep}u=$user&t=$tok&s=$salt" -w '\n[%{http_code}]\n'
fi
