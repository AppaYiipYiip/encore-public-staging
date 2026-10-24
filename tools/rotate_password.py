#!/usr/bin/env python3
"""Rotates the password of a test account on an Encore server, without ever printing it (docs/guides, `local/credentials-map.md` rule 4: a secret that
reaches a log, a transcript or a screenshot is rotated).

    python -I tools/rotate_password.py local/logins/encore-devvm-login.txt

The file has `address:`, `user:` and `password:` lines. The script signs in with the old password, changes it (`POST /encore/api/v1/me/password`, which
signs the account's other devices out), checks that the new one signs in, and only then writes it into the file's `password:` line. The new password is
24 random letters and digits. Nothing secret is printed; a failure prints only the server's sentence.
"""
import json
import re
import secrets
import string
import sys
import urllib.error
import urllib.request
from pathlib import Path


def call(base, path, body, token=None):
    request = urllib.request.Request(
        base + "/encore/api/v1" + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            sentence = json.loads(error.read())["error"]["message"]
        except Exception:  # noqa: BLE001 - only to say something readable
            sentence = f"HTTP {error.code}"
        raise SystemExit(f"{path}: {sentence}") from None


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    fields = {m.group(1).lower(): m.group(2).strip() for m in re.finditer(r"^(address|user|password):[ \t]*(.*)$", text, re.M)}
    for needed in ("address", "user", "password"):
        if not fields.get(needed):
            raise SystemExit(f"{path.name} has no {needed}: line")
    base = fields["address"].rstrip("/")
    login = call(base, "/auth/login", {"username": fields["user"], "password": fields["password"], "deviceName": "rotate_password.py", "deviceKind": "tool"})
    token = login["deviceToken"] if "deviceToken" in login else login["data"]["deviceToken"]
    new = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24))
    call(base, "/me/password", {"oldPassword": fields["password"], "newPassword": new}, token)
    check = call(base, "/auth/login", {"username": fields["user"], "password": new, "deviceName": "rotate_password.py", "deviceKind": "tool"})
    if "deviceToken" not in check and "deviceToken" not in check.get("data", {}):
        raise SystemExit("the new password does not sign in: the file was NOT changed")
    path.write_text(re.sub(r"^(password:[ \t]*).*$", lambda m: m.group(1) + new, text, count=1, flags=re.M), encoding="utf-8")
    print(f"rotated the password of {fields['user']} at {base}; {path.name} holds the new one")


if __name__ == "__main__":
    main()
