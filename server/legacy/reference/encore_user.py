#!/usr/bin/env python3
"""Add, list, check and remove people on an Encore reference server.

One command per person (docs/26):

    export ND_ADMIN_PASSWORD=...            # the Navidrome admin password
    encore_user.py --url http://localhost:4533 --admin admin add sara \\
        --music-dir /srv/music              # creates /srv/music/sara on this computer

What "add sara" does, in one go:
  1. a private library for her:  <music-root>/sara  (inside the container: /music/sara)
  2. her account (a random password, shown once)
  3. her account may see ONLY that library (plus the shared one with --shared)

Why a tool and not three clicks: when Navidrome creates an account it gives it
every library marked "defaultNewUsers", the first one included. Done by hand,
the new person silently sees the family library, or someone else's. This tool
replaces the list and then reads it back to prove it.

Standard library only. Talks to Navidrome's own admin API; nothing else.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

SHARED = "_shared"          # the folder / library everyone may share
NAME = re.compile(r"^[a-z][a-z0-9._-]{1,31}$")


class ToolError(Exception):
    """A problem with a plain-words message for the person at the keyboard."""


class Admin:
    """The little part of Navidrome's admin API this tool needs."""

    def __init__(self, base: str, user: str, password: str, timeout: float = 20.0):
        self.base = base.rstrip("/")
        self.timeout = timeout
        status, body = self._raw("POST", "/auth/login",
                                 {"username": user, "password": password}, token=None)
        try:
            self._token = json.loads(body)["token"]
        except (ValueError, KeyError):
            raise ToolError(f"Could not sign in as {user!r} (HTTP {status}). "
                            "Check the address and the admin password.") from None

    def _raw(self, method: str, path: str, payload=None, token="x"):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if token is not None:
            request.add_header("X-ND-Authorization", "Bearer " + self._token)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode()
        except OSError as error:
            raise ToolError(f"Cannot reach Navidrome at {self.base}: {error}") from None

    def call(self, method: str, path: str, payload=None):
        status, body = self._raw(method, path, payload)
        if status >= 400:
            raise ToolError(f"{method} {path} -> HTTP {status}: {body[:200]}")
        return json.loads(body) if body.strip() else None

    # --- libraries ---
    def libraries(self) -> list[dict]:
        return self.call("GET", "/api/library")

    def users(self) -> list[dict]:
        return self.call("GET", "/api/user")


def valid_name(name: str) -> str:
    if not NAME.match(name):
        raise ToolError("A name is 2-32 characters: lowercase letters, digits, '.', '_' or '-', "
                        "starting with a letter.")
    return name


def norm(path: str) -> str:
    """Compare paths without caring about the slash style or a trailing slash."""
    return path.replace("\\", "/").rstrip("/")


def is_shared(path: str) -> bool:
    return norm(path).endswith("/" + SHARED)


def library_path(music_root: str, name: str) -> str:
    sep = "\\" if "\\" in music_root else "/"
    return music_root.rstrip("/\\") + sep + name


def overlapping(path: str, others: list[str]) -> str | None:
    """A library inside another one (either way round) would share its songs."""
    mine = norm(path)
    for other in others:
        theirs = norm(other)
        if theirs != mine and (mine.startswith(theirs + "/") or theirs.startswith(mine + "/")):
            return other
    return None


def ensure_shared_is_the_only_default(admin: Admin) -> list[str]:
    """Only the shared library may be given to new accounts automatically."""
    changed = []
    for lib in admin.libraries():
        wants_default = is_shared(lib["path"])
        if lib.get("defaultNewUsers") and not wants_default:
            lib = dict(lib, defaultNewUsers=False)
            admin.call("PUT", f"/api/library/{lib['id']}", lib)
            changed.append(f"library {lib['name']!r} is no longer given to new accounts")
    return changed


def add_person(admin: Admin, name: str, *, music_root: str = "/music",
               shared: bool = True, password: str | None = None,
               create_dir: str | None = None, folder: str | None = None,
               extra_folders: list[str] | None = None) -> dict:
    """Idempotent: running it again repairs the libraries and keeps the account.

    `folder` is the person's folder under the music root when it is not called
    like the person (for example an existing collection mounted as `owner`).
    `extra_folders` are further libraries of the same person, each called
    `<name>-something` so it is clearly theirs (for example `owner-added`, the
    writable place for what they fetch when `owner` is a read-only collection)."""
    name = valid_name(name)
    folder = valid_name(folder) if folder else name
    extra_folders = [valid_name(f) for f in (extra_folders or [])]
    for extra in extra_folders:
        if not extra.startswith(name + "-"):
            raise ToolError(f"An extra folder of {name!r} must be called {name}-something (for example {name}-added), "
                            f"so it is clearly theirs; {extra!r} is not.")
    notes = ensure_shared_is_the_only_default(admin)

    path = library_path(music_root, folder)
    if create_dir:
        Path(create_dir, folder).mkdir(parents=True, exist_ok=True)
        notes.append(f"folder {Path(create_dir, folder)} is there")

    libs = {norm(lib["path"]): lib for lib in admin.libraries()}
    if norm(path) not in libs:
        clash = overlapping(path, list(libs))
        if clash:
            raise ToolError(
                f"{path} and the existing library {clash} contain each other, so one would show "
                f"the other's music. Keep the shared music in its own folder "
                f"({library_path(music_root, SHARED)}) and set SHARED_LIBRARY_PATH to it in .env "
                f"before the first start (docs/26).")
        created = admin.call("POST", "/api/library",
                             {"name": name, "path": path, "defaultNewUsers": False})
        libs = {norm(lib["path"]): lib for lib in admin.libraries()}
        notes.append(f"library {name!r} created (id {created['id']})")
    mine = libs[norm(path)]

    wanted = [mine["id"]]
    for extra in extra_folders:
        extra_path = library_path(music_root, extra)
        if create_dir:
            Path(create_dir, extra).mkdir(parents=True, exist_ok=True)
            notes.append(f"folder {Path(create_dir, extra)} is there")
        if norm(extra_path) not in libs:
            clash = overlapping(extra_path, list(libs))
            if clash:
                raise ToolError(f"{extra_path} and the existing library {clash} contain each other, "
                                "so one would show the other's music.")
            created = admin.call("POST", "/api/library", {"name": extra, "path": extra_path, "defaultNewUsers": False})
            libs = {norm(lib["path"]): lib for lib in admin.libraries()}
            notes.append(f"library {extra!r} created (id {created['id']})")
        wanted.append(libs[norm(extra_path)]["id"])
    if shared:
        shared_lib = next((lib for p, lib in libs.items() if is_shared(p)), None)
        if shared_lib:
            wanted.append(shared_lib["id"])
        else:
            notes.append("there is no shared library yet, so none was added")

    existing = next((u for u in admin.users() if u["userName"] == name), None)
    shown_password = None
    if existing is None:
        shown_password = password or secrets.token_urlsafe(12)
        made = admin.call("POST", "/api/user", {
            "userName": name, "name": name.capitalize(), "email": "",
            "password": shown_password, "isAdmin": False})
        user_id = made["id"]
        notes.append(f"account {name!r} created")
    else:
        user_id = existing["id"]
        notes.append(f"account {name!r} already exists; its libraries are repaired")

    # Replace, never add: a new account starts with the default libraries.
    admin.call("PUT", f"/api/user/{user_id}/library", {"libraryIds": sorted(set(wanted))})
    after = admin.call("GET", f"/api/user/{user_id}")
    got = sorted(lib["id"] for lib in after.get("libraries", []))
    if got != sorted(set(wanted)):
        raise ToolError(f"{name!r} ended up with libraries {got}, expected {sorted(set(wanted))}")
    return {"name": name, "id": user_id, "password": shown_password,
            "libraries": [lib["name"] for lib in after["libraries"]], "notes": notes}


def audit(admin: Admin) -> list[str]:
    """Plain-words findings; empty means every person sees only what they should."""
    findings = []
    libs = {lib["id"]: lib for lib in admin.libraries()}
    for lib in libs.values():
        if lib.get("defaultNewUsers") and not is_shared(lib["path"]):
            findings.append(f"library {lib['name']!r} is given to every NEW account automatically")
        clash = overlapping(lib["path"], [o["path"] for o in libs.values()])
        if clash:
            findings.append(f"library {lib['name']!r} ({lib['path']}) overlaps {clash}")
    everyone = {u["userName"] for u in admin.users()}
    for user in admin.users():
        if user.get("isAdmin"):
            continue
        for lib in user.get("libraries", []):
            path = norm(lib["path"])
            me = user["userName"]
            # An extra library of theirs is called <name>-something; but a library that is another PERSON's own
            # (sara-b's, seen by sara) must never pass for it.
            extra_of_mine = lib["name"].startswith(me + "-") and lib["name"] not in everyone
            if is_shared(path) or path.endswith("/" + me) or lib["name"] == me or extra_of_mine:
                continue
            findings.append(f"{me} can see library {lib['name']!r}, which is not theirs")
    return findings


def remove_person(admin: Admin, name: str, *, delete_library: bool = False) -> list[str]:
    name = valid_name(name)
    notes = []
    user = next((u for u in admin.users() if u["userName"] == name), None)
    if user:
        admin.call("DELETE", f"/api/user/{user['id']}")
        notes.append(f"account {name!r} removed (their music files were not touched)")
    if delete_library:
        for lib in admin.libraries():
            if lib["name"] == name or norm(lib["path"]).endswith("/" + name):
                admin.call("DELETE", f"/api/library/{lib['id']}")
                notes.append(f"library {name!r} removed from Navidrome (the folder stays on disk)")
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default=os.environ.get("ND_URL", "http://localhost:4533"))
    parser.add_argument("--admin", default=os.environ.get("ND_ADMIN_USER", "admin"))
    parser.add_argument("--password-env", default="ND_ADMIN_PASSWORD",
                        help="environment variable that holds the admin password")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="add a person with a private library")
    add.add_argument("name")
    add.add_argument("--music-root", default="/music",
                     help="where the music is INSIDE the container (default /music)")
    add.add_argument("--music-dir", help="create the person's folder here on this computer")
    add.add_argument("--folder", help="the person's folder under the music root, if it is not called like the person")
    add.add_argument("--also", action="append", default=[], metavar="NAME-FOLDER",
                     help="a further library of the same person, called <name>-something (repeat for several); "
                          "for example --also owner-added, the writable place for what they fetch")
    add.add_argument("--no-shared", action="store_true", help="do not give the shared library")
    add.add_argument("--password", help="choose a password instead of a random one")

    sub.add_parser("list", help="who can see which library")
    sub.add_parser("check", help="report anyone who can see what is not theirs")
    remove = sub.add_parser("remove", help="remove a person's account")
    remove.add_argument("name")
    remove.add_argument("--delete-library", action="store_true")

    args = parser.parse_args(argv)
    password = os.environ.get(args.password_env)
    if not password:
        print(f"Set {args.password_env} to the Navidrome admin password.", file=sys.stderr)
        return 2
    try:
        admin = Admin(args.url, args.admin, password)
        if args.command == "add":
            result = add_person(admin, args.name, music_root=args.music_root,
                                shared=not args.no_shared, password=args.password,
                                create_dir=args.music_dir, folder=args.folder, extra_folders=args.also)
            for note in result["notes"]:
                print("-", note)
            print(f"{result['name']} can see: {', '.join(result['libraries'])}")
            if result["password"]:
                print(f"Password (shown once): {result['password']}")
        elif args.command == "list":
            for user in admin.users():
                print(f"{user['userName']:16} {'admin ' if user.get('isAdmin') else 'person'} "
                      + ", ".join(lib["name"] for lib in user.get("libraries", [])))
        elif args.command == "check":
            findings = audit(admin)
            for line in findings:
                print("!", line)
            print("everyone sees only what they should" if not findings else
                  f"{len(findings)} thing(s) to fix: run `add <name>` again to repair")
            return 1 if findings else 0
        elif args.command == "remove":
            for note in remove_person(admin, args.name, delete_library=args.delete_library):
                print("-", note)
    except ToolError as error:
        print("error:", error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
