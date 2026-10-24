#!/usr/bin/env python3
"""Lists the devices an Encore account has signed in on (`GET /encore/api/v1/me/devices`), for a walk that must show a device appear or go.

    python -I devices_of.py local/logins/encore-devvm-login.txt

Reads `address:`, `user:` and `password:` from the login file and asks with the music server's token login (so it adds no device of its own). Prints
only each device's id, name and when it was last seen, never the password or a token.
"""
import hashlib
import json
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    fields = {m.group(1).lower(): m.group(2).strip() for m in re.finditer(r"^(address|user|password):[ \t]*(.*)$", text, re.M)}
    salt = secrets.token_hex(6)
    query = urllib.parse.urlencode({"u": fields["user"], "s": salt, "t": hashlib.md5((fields["password"] + salt).encode()).hexdigest()})
    url = f"{fields['address'].rstrip('/')}/encore/api/v1/me/devices?{query}"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            items = json.loads(response.read())["items"]
    except urllib.error.HTTPError as error:
        try:
            sentence = json.loads(error.read())["error"]["message"]
        except Exception:  # noqa: BLE001 - only to say something readable
            sentence = f"HTTP {error.code}"
        raise SystemExit(f"the server said: {sentence}") from None
    print(f"{len(items)} devices for {fields['user']}:")
    for item in items:
        print(f"  {item.get('id')}  {item.get('name')!s:24}  last seen {item.get('lastSeen')}")


if __name__ == "__main__":
    main()
