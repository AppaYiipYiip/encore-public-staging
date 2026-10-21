"""The only things this website does with Docker, and nothing else (docs/45b section 6, ADR-106).

Docker's control socket is as powerful as root on the machine, so this file is the whole of what the admin may ask of it:
one image (the sign-in browser, named in the settings), one kind of container (named `encore-signin-` and eight letters or
digits, labelled so leftovers can be found), made from a fixed template. No caller supplies a command, an image, a mount, a
network or a capability: the template has the only knobs (the window's name, its profile folder, the stack's network). Anything else is refused here, before it reaches Docker.
"""
from __future__ import annotations

import http.client
import io
import json
import re
import socket
import struct
import tarfile
import urllib.parse
from typing import Callable

from . import redact

#: `(method, path, body) -> (status, bytes)`; the real one talks to the socket, the tests' one is a fake.
Transport = Callable[[str, str, object], "tuple[int, bytes]"]

NAME = re.compile(r"encore-signin-[a-z0-9]{8}")
#: The containers of the stack itself (their `container_name` in the compose file). Reading is all that is done with them here.
STACK = ("navidrome", "encore-people", "encore-fetch", "encore-hub", "encore-admin", "encore-tailscale", "caddy",
         "encore-quality", "encore-lidarr", "encore-slskd", "encore-soularr", "encore-recs")
LABEL = "app.encore.signin"
#: What the sign-in window starts on: Google's own sign-in page, then YouTube.
START_URL = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F"


class DockerError(Exception):
    """Docker said no (or could not be reached); the message is for the log, not for the person."""


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float | None) -> None:
        super().__init__("docker", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if self.timeout is not None:
            self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def unix_transport(path: str, timeout: float | None = 30.0) -> Transport:
    def call(method: str, url: str, body: object = None) -> tuple[int, bytes]:
        connection = _UnixConnection(path, timeout)
        try:
            headers = {"Host": "docker"}
            payload = None
            if body is not None:
                payload = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            connection.request(method, url, body=payload, headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        except OSError as error:
            raise DockerError(f"cannot reach Docker: {error}") from error
        finally:
            connection.close()

    return call


class Docker:
    def __init__(self, transport: Transport, pull_transport: Transport | None, image: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*(:[A-Za-z0-9._-]+)?", image):
            raise ValueError("that is not an image name")
        self._call = transport
        self._pull = pull_transport or transport
        self._image = image

    # ------------------------------------------------------------------ the image

    def image_present(self) -> bool:
        status, _ = self._call("GET", f"/images/{urllib.parse.quote(self._image, safe='')}/json", None)
        return status == 200

    def pull(self) -> None:
        """Downloads the sign-in browser (about 1.5 GB, the first time only). Blocks until it is there."""
        repository, _, tag = self._image.rpartition(":")
        if not repository or "/" in tag:  # no tag given ("host:5000/name" has a colon but no tag)
            repository, tag = self._image, "latest"
        query = urllib.parse.urlencode({"fromImage": repository, "tag": tag})
        status, data = self._pull("POST", f"/images/create?{query}", None)
        if status != 200:
            raise DockerError(f"pull failed ({status})")
        for line in data.decode("utf-8", "replace").splitlines():
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("error"):
                raise DockerError(f"pull failed: {str(message['error'])[:200]}")

    # ------------------------------------------------------------------ the one kind of container

    def _check(self, name: str) -> str:
        if not NAME.fullmatch(name):
            raise DockerError("not a sign-in window")
        return name

    def create(self, name: str, *, network: str) -> None:
        """A fresh Firefox with an empty profile (its cookies are a plain file, so the sign-in can be read out of it), no more
        than 1 GB of memory and no restart. It publishes **no port** to the machine: it joins the stack's own network and the
        admin website shows it, inside its own page, after checking who is asking, so the only way to it is through the signed-in
        owner's page (and it needs no password of its own). Its profile lives inside the container (the image's own volume, deleted
        with it): nothing is shared with the host, so this works the same on any system that runs Docker."""
        self._check(name)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}", network):
            raise DockerError("bad network name")
        config = {
            "Image": self._image,
            "Env": [
                "USER_ID=1000", "GROUP_ID=1000", "TZ=UTC", "DISPLAY_WIDTH=1280", "DISPLAY_HEIGHT=800", "KEEP_APP_RUNNING=1",
                f"FF_OPEN_URL={START_URL}",
            ],
            "Labels": {LABEL: "1"},
            "HostConfig": {
                "NetworkMode": network,
                "ShmSize": 512 * 1024 * 1024,
                "Memory": 1024 * 1024 * 1024,
                "RestartPolicy": {"Name": "no"},
            },
        }
        status, data = self._call("POST", f"/containers/create?name={name}", config)
        if status != 201:
            raise DockerError(f"create failed ({status}): {data.decode('utf-8', 'replace')[:200]}")

    def read_file(self, name: str, path: str, limit: int = 64 * 1024 * 1024) -> bytes | None:
        """One file out of a sign-in window's container (what `docker cp` does): its cookie file. Only files below `/config` of one of
        our windows; `None` when the file is not there."""
        self._check(name)
        if not re.fullmatch(r"/config/[A-Za-z0-9_./-]+", path) or ".." in path:
            raise DockerError("not a file of a sign-in window")
        status, data = self._call("GET", f"/containers/{name}/archive?path={urllib.parse.quote(path, safe='')}", None)
        if status == 404:
            return None
        if status != 200:
            raise DockerError(f"copy failed ({status})")
        try:
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                member = next((m for m in archive.getmembers() if m.isfile()), None)
                if member is None or member.size > limit:
                    return None
                handle = archive.extractfile(member)
                return handle.read() if handle else None
        except tarfile.TarError:
            return None

    def start(self, name: str) -> None:
        status, data = self._call("POST", f"/containers/{self._check(name)}/start", None)
        if status not in (204, 304):
            raise DockerError(f"start failed ({status}): {data.decode('utf-8', 'replace')[:200]}")

    def running(self, name: str) -> bool:
        status, data = self._call("GET", f"/containers/{self._check(name)}/json", None)
        if status != 200:
            return False
        try:
            return bool(json.loads(data).get("State", {}).get("Running"))
        except ValueError:
            return False

    def stop(self, name: str, seconds: int = 15) -> None:
        """A clean stop: the browser ends properly, which writes its latest cookies to its profile and ends the session (a browser
        left running changes the sign-in's cookies behind our back, and the saved copy stops working)."""
        self._call("POST", f"/containers/{self._check(name)}/stop?t={int(seconds)}", None)

    def remove(self, name: str) -> None:
        """Stops it (if it runs) and deletes it with its anonymous volumes. Not an error when it is already gone."""
        self._check(name)
        self._call("POST", f"/containers/{name}/stop?t=3", None)
        self._call("DELETE", f"/containers/{name}?force=true&v=true", None)

    def stack(self) -> dict[str, str]:
        """How each part of the stack that exists is doing: `running`, `starting` (just started, or its own check has not passed yet),
        `unhealthy`, `restarting` or `stopped`. A part that is not in the answer was never created (its profile is not switched on).
        Reading only; raises [DockerError] when Docker cannot be asked, so that "unknown" is never mistaken for "nothing runs"."""
        return {name: found["state"] for name, found in self.details().items()}

    def details(self) -> dict[str, dict]:
        """[stack] with the image each part runs: `{name: {"state", "image"}}`."""
        status, data = self._call("GET", "/containers/json?all=true", None)
        if status != 200:
            raise DockerError(f"cannot list containers ({status})")
        try:
            found = json.loads(data)
        except ValueError as error:
            raise DockerError("Docker's answer could not be read") from error
        states: dict[str, dict] = {}
        for item in found if isinstance(found, list) else []:
            if not isinstance(item, dict):
                continue
            for raw in item.get("Names", []):
                name = str(raw).lstrip("/")
                if name in STACK:
                    states[name] = {"state": _state_of(str(item.get("State", "")), str(item.get("Status", ""))), "image": str(item.get("Image", ""))[:80]}
        return states

    def restart(self, name: str, seconds: int = 10) -> None:
        """Restarts one part of the stack (only the parts named in [STACK], and never the container this website runs in). It comes back by
        itself in a few seconds; nothing is removed or changed."""
        if name not in STACK or name == "encore-admin":
            raise DockerError("that part cannot be restarted from here")
        status, data = self._call("POST", f"/containers/{name}/restart?t={int(seconds)}", None)
        if status != 204:
            raise DockerError(f"restart failed ({status}): {data.decode('utf-8', 'replace')[:200]}")

    def logs(self, name: str, tail: int = 200) -> list[str]:
        """The last [tail] lines a part of the stack said, with anything that looks like a key or a password hidden."""
        if name not in STACK:
            raise DockerError("that is not a part of the stack")
        status, data = self._call("GET", f"/containers/{name}/logs?stdout=1&stderr=1&tail={max(1, min(int(tail), 1000))}", None)
        if status != 200:
            raise DockerError(f"cannot read the messages ({status})")
        text = _unframe(data).decode("utf-8", "replace")
        return [redact.line(line.rstrip()) for line in text.splitlines()[-tail:] if line.strip()]

    def leftovers(self) -> list[str]:
        """Sign-in windows that exist (a restart of the website forgot them)."""
        filters = urllib.parse.quote(json.dumps({"label": [f"{LABEL}=1"]}))
        status, data = self._call("GET", f"/containers/json?all=true&filters={filters}", None)
        if status != 200:
            return []
        try:
            found = json.loads(data)
        except ValueError:
            return []
        names = []
        for item in found if isinstance(found, list) else []:
            for raw in item.get("Names", []):
                name = str(raw).lstrip("/")
                if NAME.fullmatch(name):
                    names.append(name)
        return names


_UP_SECONDS = re.compile(r"Up (?:Less than a second|\d+ seconds?)")


def _state_of(state: str, status: str) -> str:
    if state == "restarting":
        return "restarting"
    if state != "running":
        return "stopped"
    if "unhealthy" in status:
        return "unhealthy"
    if "health: starting" in status or _UP_SECONDS.match(status):
        return "starting"
    return "running"


def _unframe(data: bytes) -> bytes:
    """A container's messages come as frames (8 bytes: which stream, three zeros, the length; then the text) unless it has a terminal, when
    they are plain text. Either way, the text."""
    out, at = [], 0
    while at + 8 <= len(data):
        kind, zeros, size = data[at], data[at + 1:at + 4], struct.unpack(">I", data[at + 4:at + 8])[0]
        if kind not in (0, 1, 2) or zeros != b"\x00\x00\x00" or at + 8 + size > len(data):
            break
        out.append(data[at + 8:at + 8 + size])
        at += 8 + size
    return b"".join(out) if out and at == len(data) else data
