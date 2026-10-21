#!/usr/bin/env bash
# On the dev VM: call any Encore service as the owner or as the guest.  qs.sh CONTAINER PORT owner|guest METHOD PATH [json]
set -euo pipefail
. ~/encore-creds.txt
svc="$1"; port="$2"; who="$3"; method="$4"; path="$5"; body="${6:-}"
if [[ $who == owner ]]; then user="$OWNER"; pw="$OWNER_PW"; else user="$GUEST"; pw="$GUEST_PW"; fi
IP=$(docker inspect -f '{{(index .NetworkSettings.Networks "encore-server_default").IPAddress}}' "$svc")
salt=$(openssl rand -hex 6); tok=$(printf '%s%s' "$pw" "$salt" | md5sum | cut -d' ' -f1)
sep='?'; [[ $path == *\?* ]] && sep='&'
if [[ -n $body ]]; then
  curl -s -m 120 -X "$method" "http://$IP:$port${path}${sep}u=$user&t=$tok&s=$salt" -H 'Content-Type: application/json' -d "$body" -w '\n[%{http_code}]\n'
else
  curl -s -m 120 -X "$method" "http://$IP:$port${path}${sep}u=$user&t=$tok&s=$salt" -w '\n[%{http_code}]\n'
fi
