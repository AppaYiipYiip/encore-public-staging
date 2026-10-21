#!/usr/bin/env python3
"""Proves the reference server's recommendations against a REAL Navidrome.

    python check_reference.py --navidrome path/to/navidrome --ffmpeg path/to/ffmpeg

The guide (docs/26) recommends a set of Navidrome settings. A setting that is
misspelt is silently ignored by Navidrome, so "it is in the compose file" proves
nothing. This script starts the real binary with those settings on a throw-away
copy (own port, own folders, a few generated songs) and checks the behaviour
each setting is supposed to give. It also checks that compose.yaml still says
the same thing as REFERENCE_ENV below, so the guide, the file and the proof
cannot drift apart.

Standard library only. Exit code 0 = everything passed (skipped checks are
reported but do not fail); 1 = something failed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPOSE = HERE.parent / "compose.yaml"
sys.path.insert(0, str(HERE.parent))
import encore_user  # noqa: E402  (the tool people run to add a person)

# The single source of truth for the recommended settings. compose.yaml must
# carry exactly these values for the navidrome service.
REFERENCE_ENV = {
    "ND_SCANSCHEDULE": "@every 1h",
    "ND_LOGLEVEL": "info",
    "ND_SESSIONTIMEOUT": "720h",
    "ND_ENABLEINSIGHTSCOLLECTOR": "false",
    "ND_ENABLESHARING": "false",
    "ND_ENABLETRANSCODINGCONFIG": "false",
    "ND_BACKUP_PATH": "/data/backup",
    "ND_BACKUP_SCHEDULE": "0 3 * * *",
    "ND_BACKUP_COUNT": "7",
    "ND_LYRICSPRIORITY": ".lrc,embedded",
}
CONTAINER_FIXED = {"ND_MUSICFOLDER": "/music", "ND_DATAFOLDER": "/data"}
# Empty unless a proxy sits in front (docs/33 section 6, T5). Both or neither: see the init helper and proxy_checks().
PROXY_ENV = {"ND_EXTAUTH_TRUSTEDSOURCES": "", "ND_EXTAUTH_USERHEADER": ""}

results: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"{status:5} {name}" + (f"  - {detail}" if detail else ""), flush=True)


def check(name: str):
    """Run a check; a raised AssertionError / error becomes a FAIL line."""

    def wrap(fn):
        try:
            outcome = fn()
        except AssertionError as error:
            record("FAIL", name, str(error))
        except Exception as error:  # noqa: BLE001 - report, never crash the run
            record("FAIL", name, f"{type(error).__name__}: {error}")
        else:
            if isinstance(outcome, str) and outcome.startswith("SKIP:"):
                record("SKIP", name, outcome[5:].strip())
            else:
                record("PASS", name, outcome if isinstance(outcome, str) else "")
        return fn

    return wrap


# --------------------------------------------------------------------- helpers


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method: str, url: str, body: dict | None = None, timeout: float = 20.0,
         limit: int | None = None, headers: dict | None = None):
    """-> (status, headers, bytes). Never raises on an HTTP error status."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read(limit)
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def make_tracks(ffmpeg: str, music: Path) -> None:
    """Three tiny songs in the layout the guide recommends."""
    specs = [
        ("Artist A", "Album One (2020)", "01 - First.flac", "First", 1, "flac", []),
        ("Artist A", "Album One (2020)", "02 - Second.opus", "Second", 2, "libopus",
         ["-b:a", "96k"]),
        ("Artist B", "Album Two (2019)", "01 - Third.mp3", "Third", 1, "libmp3lame",
         ["-b:a", "128k"]),
    ]
    for artist, album, filename, title, number, codec, extra in specs:
        target = music / artist / album / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        year = album.split("(")[1].rstrip(")")
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=3", "-metadata", f"title={title}",
             "-metadata", f"artist={artist}", "-metadata", f"album_artist={artist}",
             "-metadata", f"album={album.split(' (')[0]}", "-metadata",
             f"track={number}", "-metadata", f"date={year}", "-c:a", codec, *extra,
             str(target)],
            check=True,
        )
    (music / "Artist A" / "Album One (2020)" / "01 - First.lrc").write_text(
        "[00:00.50]first line\n[00:01.50]second line\n[00:02.50]third line\n",
        encoding="utf-8")


def tree_state(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*")) if p.is_file()
    }


class Navidrome:
    def __init__(self, binary: str, ffmpeg_dir: str, work: Path,
                 music_folder: Path | None = None):
        self.binary = binary
        self.work = work
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.env = os.environ.copy()
        self.env["PATH"] = ffmpeg_dir + os.pathsep + self.env.get("PATH", "")
        for key, value in REFERENCE_ENV.items():
            self.env[key] = value.replace("/data", str(work / "data"))
        # Only so the check does not wait until 03:00: the same setting, faster.
        self.env["ND_BACKUP_SCHEDULE"] = "@every 2s"
        self.env["ND_BACKUP_COUNT"] = "2"
        self.env["ND_MUSICFOLDER"] = str(music_folder or work / "music")
        self.env["ND_DATAFOLDER"] = str(work / "data")
        self.env["ND_ADDRESS"] = "127.0.0.1"
        self.env["ND_PORT"] = str(self.port)
        self.env["ND_SCANSCHEDULE"] = "@every 1h"
        self.proc: subprocess.Popen | None = None
        self.user = "checker"
        self.password = "check-" + hashlib.sha1(str(time.time()).encode()).hexdigest()[:10]

    def start(self) -> None:
        log = open(self.work / "navidrome.log", "wb")
        self.proc = subprocess.Popen([self.binary, "--nobanner"], env=self.env,
                                     stdout=log, stderr=log, cwd=self.work)
        deadline = time.time() + 40
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("navidrome exited: see " + str(self.work / "navidrome.log"))
            try:
                status, _, _ = http("GET", self.base + "/ping", timeout=2)
                if status == 200:
                    return
            except OSError:
                pass
            time.sleep(0.4)
        raise RuntimeError("navidrome did not answer /ping within 40 s")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([self.binary, "--nobanner", *args], env=self.env,
                              capture_output=True, text=True, timeout=60, cwd=self.work)

    def subsonic(self, method: str, **params):
        return self.subsonic_as(self.user, self.password, method, **params)

    def subsonic_as(self, user: str, password: str, method: str, headers: dict | None = None, **params):
        salt = "s" + hashlib.md5(os.urandom(8)).hexdigest()[:8]
        token = hashlib.md5((password + salt).encode()).hexdigest()
        query = urllib.parse.urlencode({"u": user, "t": token, "s": salt,
                                        "v": "1.16.1", "c": "check", "f": "json", **params})
        return http("GET", f"{self.base}/rest/{method}?{query}", limit=400_000, headers=headers)


def wait_until(predicate, seconds: float, what: str):
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.4)
    raise AssertionError(f"timed out waiting for {what}")


# ---------------------------------------------------------------------- checks


def _check_proxy_guard(docker: str, init: dict, image_of_init: str) -> None:
    """Trusting a proxy (to see real client addresses) also lets it log people in by a header, unless that header has a
    secret name (E3/E4 in proxy_checks). The helper must therefore stop the stack when only one of the two is set."""
    if sys.platform != "linux":
        return  # runs the real helper image; a Linux Docker engine is needed
    command = init["command"]
    assert command[:2] == ["sh", "-c"], f"unexpected helper command {command[:2]}"
    cases = [  # (trusted sources, header, must start)
        ("", "", True),                                         # no proxy: nothing to guard
        ("172.16.0.0/12", "X-Encore-0123456789abcdef0123456789abcdef", True),
        ("172.16.0.0/12", "", False),                           # trusted but no header name
        ("172.16.0.0/12", "Remote-User", False),                # the default name: guessable
        ("172.16.0.0/12", "remote-USER", False),                # in any case
        ("172.16.0.0/12", "X-Short", False),                    # too short to be a secret
    ]
    with tempfile.TemporaryDirectory(prefix="encore-guard-") as tmp:
        for trusted, header, should_start in cases:
            done = subprocess.run(
                [docker, "run", "--rm", "--network", "none", "--entrypoint", "sh", "-e", "PUID=0", "-e", "PGID=0",
                 "-e", f"PROXY_TRUSTED_SOURCES={trusted}", "-e", f"PROXY_USER_HEADER={header}",
                 "-v", f"{tmp}:/data", "-v", f"{tmp}:/backup", image_of_init, "-c", command[2].replace("$$", "$")],
                capture_output=True, text=True, timeout=120)
            started = done.returncode == 0
            assert started == should_start, (
                f"helper with trusted={trusted!r} header={header!r}: "
                f"{'started' if started else 'refused'}, wanted {'start' if should_start else 'refusal'} "
                f"({(done.stdout + done.stderr).strip()[:160]!r})")


def setup_checks() -> None:
    """setup.sh is what a first-time operator runs. It is proved here against a stand-in `docker` that records what it was asked."""
    bash = shutil.which("bash")
    if not bash or sys.platform == "win32":
        record("SKIP", "setup.sh behaviour", "needs bash on Linux or macOS")
        return

    shim = """#!/bin/bash
echo "docker $*" >> "$SHIM_LOG"
case "$1" in
  info) exit 0 ;;
  inspect)
    case "$*" in
      # The sidecar only exists (and is connected) once the stack has been started.
      *encore-tailscale*) if [ -f "$SHIM_STATE" ]; then echo healthy; exit 0; else exit 1; fi ;;
      *) echo healthy; exit 0 ;;
    esac ;;
  exec) echo '"DNSName": "music.tail-test.ts.net.",'; exit 0 ;;
  compose)
    case "$2" in
      version) echo "Docker Compose version v2.99"; exit 0 ;;
      up) grep -E '^(TS_AUTHKEY|COMPOSE_PROFILES)=' .env | sed 's/^/at-up: /' >> "$SHIM_LOG"; touch "$SHIM_STATE"; exit 0 ;;
      logs) echo "To authenticate, visit: https://login.tailscale.com/a/shim"; exit 0 ;;
    esac ;;
esac
exit 0
"""

    def parse(path: Path) -> dict[str, str]:
        out = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                out[key] = value
        return out

    @check("setup.sh: asks for the music folder and a pasted key, writes .env, makes the secret header, is safe to run twice")
    def _():
        with tempfile.TemporaryDirectory(prefix="encore-setup-") as tmp:
            kit = Path(tmp) / "kit"
            shutil.copytree(HERE.parent, kit, ignore=shutil.ignore_patterns("tests", "__pycache__", "data", ".env"))
            fake = Path(tmp) / "bin"
            fake.mkdir()
            (fake / "docker").write_text(shim, encoding="utf-8", newline="\n")
            (fake / "docker").chmod(0o755)
            music = Path(tmp) / "my music"  # a space on purpose
            log = Path(tmp) / "docker.log"
            env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "SHIM_LOG": str(log),
                   "SHIM_STATE": str(Path(tmp) / "stack-up"), "FUNNEL": "1", "HOME": tmp}

            def run(stdin: str) -> subprocess.CompletedProcess:
                return subprocess.run([bash, "setup.sh", str(music)], cwd=kit, input=stdin, env=env,
                                      capture_output=True, text=True, timeout=120)

            first = run("tskey-auth-kTEST12345-abcdefghijklmnop\n")
            assert first.returncode == 0, "first run failed: " + (first.stdout + first.stderr)[-400:]
            dotenv = parse(kit / ".env")
            assert Path(dotenv["MUSIC_DIR"]).resolve() == music.resolve() and music.is_dir(), dotenv.get("MUSIC_DIR")
            assert dotenv["COMPOSE_PROFILES"] == "funnel", "the funnel profile must be switched on in .env"
            assert dotenv["PROXY_TRUSTED_SOURCES"] == "172.16.0.0/12", dotenv.get("PROXY_TRUSTED_SOURCES")
            header = dotenv["PROXY_USER_HEADER"]
            assert header.startswith("X-Encore-") and len(header) >= 32 and header.lower() != "remote-user", header
            logged = log.read_text(encoding="utf-8")
            assert "at-up: TS_AUTHKEY=tskey-auth-kTEST12345-abcdefghijklmnop" in logged, \
                "the pasted key must be in .env when the stack starts"
            assert dotenv.get("TS_AUTHKEY", "") == "", "the one-time key must be removed from .env once connected"
            assert "https://music.tail-test.ts.net" in first.stdout, "it should print the address: " + first.stdout[-300:]
            assert dotenv.get("PUBLIC_URL") == "https://music.tail-test.ts.net", \
                "the public address must be remembered in .env: invitations are links on it (docs/35)"
            assert "kTEST12345-abcdefghijklmnop" not in first.stdout + first.stderr, "the key must never be printed"
            mode = (kit / ".env").stat().st_mode & 0o077
            assert mode == 0, "the .env that held a key must not be readable by others"

            # Second run: the sidecar is connected now; nothing is asked and nothing changes (no new secret header, no key).
            before = (kit / ".env").read_text(encoding="utf-8")
            second = run("")
            assert second.returncode == 0, "second run failed: " + (second.stdout + second.stderr)[-400:]
            assert (kit / ".env").read_text(encoding="utf-8") == before, "a second run changed .env"
            assert "Key (typing is hidden)" not in second.stdout, "a connected machine was asked for a key again"
        return "key taken and removed again, secret header made once, music folder with a space handled"


def static_checks() -> None:
    @check("compose.yaml is valid and says what the settings table says")
    def _():
        docker = shutil.which("docker")
        if not docker:
            return "SKIP: docker is not installed here (the file is checked on a machine that has it)"
        env = os.environ.copy()
        # Level 0 as a person types it: only MUSIC_DIR set, no profile. This once
        # failed ("DOMAIN is required") because Compose checks required variables
        # even for services that are switched off.
        plain = subprocess.run(
            [docker, "compose", "-f", str(COMPOSE), "config", "--format", "json"],
            capture_output=True, text=True, env={**env, "MUSIC_DIR": "/srv/music"}, timeout=60)
        assert plain.returncode == 0, "Level 0 does not start: " + plain.stderr.strip()[:300]
        # Level 0 = Navidrome plus the one-shot helper that gives it a writable data folder (see compose.yaml).
        assert set(json.loads(plain.stdout)["services"]) == {"navidrome", "navidrome-init"}, \
            "the optional services must stay off until their profile is asked for"
        env.update({"MUSIC_DIR": "/srv/music", "DOMAIN": "music.example.org"})
        done = subprocess.run(
            [docker, "compose", "-f", str(COMPOSE), "--profile", "https",
             "--profile", "kit", "config", "--format", "json"],
            capture_output=True, text=True, env=env, timeout=60)
        assert done.returncode == 0, "docker compose config failed: " + done.stderr.strip()[:300]
        config = json.loads(done.stdout)
        service = config["services"]["navidrome"]

        image = service["image"]
        assert ":" in image and not image.endswith(":latest"), f"image is not pinned: {image}"
        assert image.split(":")[1][0].isdigit(), f"image tag is not a version: {image}"

        env_now = {k: str(v) for k, v in service["environment"].items()}
        for key, value in {**REFERENCE_ENV, **CONTAINER_FIXED, **PROXY_ENV}.items():
            assert env_now.get(key) == value, f"{key} is {env_now.get(key)!r}, expected {value!r}"
        unexpected = [k for k in env_now if k.startswith("ND_")
                      and k not in REFERENCE_ENV and k not in CONTAINER_FIXED and k not in PROXY_ENV]
        assert not unexpected, f"settings in compose.yaml but not in the proof: {unexpected}"

        music = [v for v in service["volumes"] if v["target"] == "/music"]
        assert music and music[0].get("read_only") is True, "/music must be mounted read-only"
        assert str(service.get("user", "")).split(":")[0] not in ("", "0", "root"), "runs as root"
        assert "no-new-privileges:true" in service.get("security_opt", []), "no-new-privileges missing"
        assert "ALL" in service.get("cap_drop", []), "capabilities are not dropped"
        # A clean machine: Docker creates a missing data folder as root, so without this helper Navidrome (not root)
        # fails with "unable to open database file". Proved on a Docker engine in docs/25 (entry 44).
        init = config["services"]["navidrome-init"]
        assert service.get("depends_on", {}).get("navidrome-init", {}).get("condition") == "service_completed_successfully", \
            "Navidrome must wait for the data-folder helper to finish"
        assert init["restart"] == "no" and init["network_mode"] == "none", "the helper runs once, offline"
        assert ":" in init["image"] and not init["image"].endswith(":latest"), f"helper image is not pinned: {init['image']}"
        assert {"/data", "/backup"} == {v["target"] for v in init["volumes"]}, "the helper must own exactly data and backup"
        assert not any(v["target"] == "/music" for v in init["volumes"]), "the helper must never see the music"
        assert init.get("cap_add") == ["CHOWN"] and "ALL" in init.get("cap_drop", []), "helper has more rights than chown"
        _check_proxy_guard(docker, init, image_of_init=init["image"])
        for name, svc in config["services"].items():
            assert not svc.get("privileged"), f"{name} is privileged"
            assert svc.get("network_mode") != "host", f"{name} uses the host network"
        assert not config["services"]["caddy"]["image"].endswith(":latest")
        # The same clean-machine trap as Navidrome's data folder (ADR-082): Docker creates the kit's scratch folder as root and the service
        # runs as an ordinary user. Found on the owner's server (the first fetch failed with PermissionError).
        kit = config["services"]["encore-fetch"]
        assert kit.get("depends_on", {}).get("kit-init", {}).get("condition") == "service_completed_successfully", \
            "the fetch service must wait for the helper that gives it a writable scratch folder"
        kit_init = config["services"]["kit-init"]
        assert {v["target"] for v in kit_init["volumes"]} == {"/work", "/people-data"}, \
            "the kit helper must own exactly the two scratch folders (fetch and people)"
        assert kit_init["restart"] == "no" and kit_init["network_mode"] == "none", "the helper runs once, offline"
        assert ":" in kit_init["image"] and not kit_init["image"].endswith(":latest"), "helper image is not pinned"
        assert kit_init.get("cap_add") == ["CHOWN"] and "ALL" in kit_init.get("cap_drop", []), "helper has more rights than chown"
        kit_env = config["services"]["encore-fetch"]["environment"]
        assert str(kit_env.get("PEOPLE")) == "0" and "PERSON_FOLDERS" in kit_env, \
            "the kit must know about the one-library-per-person layout (off by default)"
        return f"image {image}, {len(REFERENCE_ENV)} settings match"

    @check("funnel profile: a Tailscale sidecar that publishes Navidrome, /people, /fetch and /hub and nothing else (docs/33, docs/35, ADR-094, ADR-095)")
    def _():
        docker = shutil.which("docker")
        if not docker:
            return "SKIP: docker is not installed here (the file is checked on a machine that has it)"
        # No TS_AUTHKEY on purpose: the first start must work by signing in with a link in the log.
        env = {k: v for k, v in os.environ.items() if k != "TS_AUTHKEY"}
        env["MUSIC_DIR"] = "/srv/music"
        done = subprocess.run(
            [docker, "compose", "-f", str(COMPOSE), "--profile", "funnel", "config", "--format", "json"],
            capture_output=True, text=True, env=env, timeout=60)
        assert done.returncode == 0, "the funnel profile does not start without a key: " + done.stderr.strip()[:300]
        config = json.loads(done.stdout)
        assert set(config["services"]) == {"navidrome", "navidrome-init", "tailscale"}, \
            f"funnel adds exactly one service, got {sorted(config['services'])}"
        ts = config["services"]["tailscale"]
        tag = ts["image"].split(":")[-1]
        assert ts["image"].startswith("tailscale/tailscale:") and tag[:1] == "v" and tag[1:2].isdigit(), \
            f"image is not pinned to a version: {ts['image']}"
        settings = {k: str(v) for k, v in ts["environment"].items()}
        assert settings.get("TS_USERSPACE") == "true", "must run in userspace mode (no tun device, no NET_ADMIN)"
        assert settings.get("TS_SERVE_CONFIG") == "/config/serve.json", "the public surface must come from the serve file"
        assert not ts.get("devices"), "no device passed through (/dev/net/tun is not needed in userspace mode)"
        assert not ts.get("cap_add"), "no added capabilities"
        assert ts.get("network_mode") != "host" and not ts.get("privileged"), "host network / privileged"
        assert not ts.get("ports"), "the sidecar publishes no port; the public side is Tailscale's"
        assert "no-new-privileges:true" in ts.get("security_opt", []), "no-new-privileges missing"
        mounts = {v["target"]: v for v in ts["volumes"]}
        assert "/var/lib/tailscale" in mounts, "state must persist, or every restart registers a new machine"
        assert mounts.get("/config", {}).get("read_only") is True, "the serve file is mounted read-only"
        assert "/music" not in mounts, "the sidecar never sees the music"
        assert ts.get("healthcheck"), "a health check tells the operator when the sidecar is not connected"
        assert ts["restart"] == "unless-stopped", "restart policy"
        serve = json.loads((COMPOSE.parent / "tailscale" / "serve.json").read_text(encoding="utf-8"))
        sites = serve["Web"]
        assert set(sites) == set(serve["AllowFunnel"]) and all(serve["AllowFunnel"].values()), \
            "every published site must be listed in AllowFunnel, and nothing else"
        published = [(path, handler) for site in sites.values() for path, handler in site["Handlers"].items()]
        # Exactly these three: Navidrome (ADR-083); the people service under /people (ADR-087: the invitation page and the friend-activity
        # API, both of which refuse anything without a valid invitation or the music server's own token); and the instant-play service under
        # /fetch (ADR-094: every route but /api/info needs the music server's token, and a person is limited to a number of songs a day);
        # and the Jam hub under /hub (ADR-095: every route but /api/info and /api/time needs the music server's token, and wrong logins are
        # slowed down). A friend who is away from home has no other door to "play any song" or to a Jam.
        assert sorted(published, key=lambda p: p[0]) == [("/", {"Proxy": "http://navidrome:4533"}),
                                                          ("/fetch", {"Proxy": "http://encore-fetch:8701"}),
                                                          ("/hub", {"Proxy": "http://encore-hub:8703"}),
                                                          ("/people", {"Proxy": "http://encore-people:8702"})], \
            f"Funnel may publish Navidrome, /people, /fetch and /hub and nothing else, got {published}"
        assert set(serve["TCP"]) == {"443"}, "only port 443"
        assert ts["healthcheck"]["test"][-1].endswith("/config/healthcheck.sh"), \
            "the health check must be the script that also watches the key's expiry"
        return f"image {ts['image']}, serve file publishes exactly Navidrome, /people, /fetch and /hub"

    @check("people profile: the invite and friend-activity service is hardened, publishes no port, and holds the only admin login (docs/35)")
    def _():
        docker = shutil.which("docker")
        if not docker:
            return "SKIP: docker is not installed here (the file is checked on a machine that has it)"
        env = {k: v for k, v in os.environ.items() if k not in ("PEOPLE_ADMIN_USER", "PEOPLE_ADMIN_PASSWORD")}
        env.pop("PEOPLE_INVITERS", None)
        env.pop("PEOPLE_OWNERS", None)
        env.update({"MUSIC_DIR": "/srv/music", "PEOPLE_ADMIN_USER": "encore-admin", "PEOPLE_ADMIN_PASSWORD": "s3cret-not-real",
                    "PEOPLE_OWNERS": "owner"})
        done = subprocess.run(
            [docker, "compose", "-f", str(COMPOSE), "--profile", "people", "--profile", "funnel", "config", "--format", "json"],
            capture_output=True, text=True, env=env, timeout=60)
        assert done.returncode == 0, "the people profile does not start: " + done.stderr.strip()[:300]
        config = json.loads(done.stdout)
        services = config["services"]
        assert "encore-people" in services and "kit-init" in services, sorted(services)
        svc = services["encore-people"]
        assert not svc.get("ports"), "the people service publishes no port; the sidecar reaches it over the stack's network"
        assert svc.get("user", "").split(":")[0] not in ("", "0", "root"), "must not run as root"
        assert "ALL" in svc.get("cap_drop", []) and not svc.get("cap_add"), "capabilities"
        assert "no-new-privileges:true" in svc.get("security_opt", []), "no-new-privileges missing"
        assert svc.get("read_only") is True, "a read-only root file system"
        assert svc.get("network_mode") != "host" and not svc.get("privileged")
        assert svc.get("depends_on", {}).get("kit-init", {}).get("condition") == "service_completed_successfully", \
            "the people service must wait for the helper that gives it a writable data folder"
        mounts = {v["target"]: v for v in svc["volumes"]}
        assert "/data" in mounts and "/music" in mounts, sorted(mounts)
        assert "/music" in mounts and not mounts["/music"].get("read_only"), "it makes each invited person's folder, so /music is writable here"
        environment = {k: str(v) for k, v in svc["environment"].items()}
        assert environment.get("NAVIDROME_ADMIN_USER") == "encore-admin" and environment.get("NAVIDROME_ADMIN_PASSWORD"), \
            "the service needs the administrator login to create accounts"
        assert environment.get("PEOPLE_OWNERS") == "owner", \
            "the names the operator lists as owners must reach the service (an ordinary everyday account cannot invite otherwise)"
        # The name this setting had before roles existed must keep working for servers that already use it.
        old_name = subprocess.run(
            [docker, "compose", "-f", str(COMPOSE), "--profile", "people", "--profile", "funnel", "config", "--format", "json"],
            capture_output=True, text=True, timeout=60,
            env={**{k: v for k, v in env.items() if k != "PEOPLE_OWNERS"}, "PEOPLE_INVITERS": "owner"})
        assert old_name.returncode == 0, old_name.stderr.strip()[:300]
        assert json.loads(old_name.stdout)["services"]["encore-people"]["environment"].get("PEOPLE_OWNERS") == "owner", \
            "a server that still says PEOPLE_INVITERS must keep its owners"
        for name, other in services.items():
            if name == "encore-people":
                continue
            leaked = [k for k, v in (other.get("environment") or {}).items() if "s3cret-not-real" in str(v)]
            assert not leaked, f"{name} holds the administrator password ({leaked}); only the people service may"
        assert svc["restart"] == "unless-stopped"
        return "no port, read-only, not root, no capabilities, the admin login lives only in this service"

    @check("funnel health check: red when disconnected or the key expires within 14 days, green otherwise (docs/33)")
    def _():
        docker = shutil.which("docker")
        if not docker:
            return "SKIP: docker is not installed here (the file is checked on a machine that has it)"
        if sys.platform != "linux":
            return "SKIP: runs the real Tailscale image with a throw-away local web server; needs a Linux Docker engine"
        image = "tailscale/tailscale:v1.104.1"
        script = (COMPOSE.parent / "tailscale" / "healthcheck.sh")
        assert script.exists(), "tailscale/healthcheck.sh is missing"
        # A first run pulls the image (on a slow line that takes minutes); do it once, with room, not inside a case.
        if subprocess.run([docker, "image", "inspect", image], capture_output=True).returncode != 0:
            pulled = subprocess.run([docker, "pull", "-q", image], capture_output=True, text=True, timeout=1200)
            assert pulled.returncode == 0, "could not pull " + image + ": " + pulled.stderr.strip()[:200]
        # What `tailscale status --peers=false --json` prints for Self, cut to the field that matters.
        now = time.time()

        def stamp(days: float) -> str:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + days * 86400))

        def status(expiry: str | None) -> str:
            body = {"Version": "1.104.1", "BackendState": "Running",
                    "Self": {"HostName": "music", "Online": True, "Expired": False}}
            if expiry is not None:
                body["Self"]["KeyExpiry"] = expiry
            return json.dumps(body)

        cases = [  # (name, status json or None for "no daemon", reachable health URL, expected exit, text expected)
            ("expiry switched off (field absent)", status(None), True, 0, ""),
            ("expiry switched off (zero time)", status("0001-01-01T00:00:00Z"), True, 0, ""),
            ("key good for 100 days", status(stamp(100)), True, 0, ""),
            ("key good for 15 days", status(stamp(15)), True, 0, ""),
            ("key ends in 5 days", status(stamp(5)), True, 1, "5 day"),
            ("key ended yesterday", status(stamp(-1)), True, 1, "expired"),
            ("not connected (health endpoint refuses)", status(None), False, 1, "not connected"),
        ]
        import http.server
        import threading

        class Healthz(http.server.BaseHTTPRequestHandler):  # plays the sidecar's /healthz
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        up_port, down_port = free_port(), free_port()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", up_port), Healthz)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory(prefix="encore-health-") as tmp:
                for name, body, reachable, want_code, want_text in cases:
                    Path(tmp, "status.json").write_text(body, encoding="utf-8")
                    port = up_port if reachable else down_port  # nothing listens on down_port
                    done = subprocess.run(
                        [docker, "run", "--rm", "--network", "host", "--entrypoint", "sh",
                         "-v", f"{script}:/config/healthcheck.sh:ro", "-v", f"{tmp}:/t:ro",
                         "-e", "TS_STATUS_FILE=/t/status.json", "-e", f"TS_HEALTH_URL=http://127.0.0.1:{port}/healthz",
                         image, "-c", "sh /config/healthcheck.sh"],
                        capture_output=True, text=True, timeout=90)
                    out = (done.stdout + done.stderr).strip()
                    assert done.returncode == want_code, \
                        f"{name}: exit {done.returncode}, wanted {want_code} ({out[:200]!r})"
                    assert want_text in out, f"{name}: the message should say {want_text!r}, got {out[:200]!r}"
        finally:
            server.shutdown()
        return f"{len(cases)} situations behave as documented"


def runtime_checks(nd: Navidrome, ffmpeg: str) -> None:
    music = nd.work / "music"
    before = tree_state(music)

    @check("starts with the recommended settings and answers /ping")
    def _():
        nd.start()
        return f"port {nd.port}"

    @check("first-run admin can be created and signs in over the Subsonic API")
    def _():
        status, _, body = http("POST", nd.base + "/auth/createAdmin",
                               {"username": nd.user, "password": nd.password})
        assert status == 200, f"createAdmin -> {status} {body[:120]!r}"
        status, _, body = nd.subsonic("ping")
        assert status == 200 and json.loads(body)["subsonic-response"]["status"] == "ok", body[:160]

    @check("scans the three songs of the recommended folder layout")
    def _():
        nd.subsonic("startScan", fullScan="true")

        def done():
            _, _, body = nd.subsonic("search3", query="", songCount="50")
            songs = json.loads(body)["subsonic-response"].get("searchResult3", {}).get("song", [])
            return songs if len(songs) == 3 else None

        nd.songs = wait_until(done, 40, "the scan to list 3 songs")
        by_title = {s["title"]: s for s in nd.songs}
        assert set(by_title) == {"First", "Second", "Third"}, set(by_title)
        assert by_title["First"].get("suffix") == "flac"
        return "3 songs, tags and years read"

    @check("transcodes a lossless file to Opus on request (remote listening)")
    def _():
        flac = next(s for s in nd.songs if s["title"] == "First")
        status, headers, body = nd.subsonic("stream", id=flac["id"], format="opus", maxBitRate="64")
        assert status == 200, f"stream -> {status} {body[:160]!r}"
        assert body[:4] == b"OggS" and b"OpusHead" in body[:200], "the answer is not an Opus stream"
        original = (music / "Artist A" / "Album One (2020)" / "01 - First.flac").stat().st_size
        assert len(body) < original, f"not smaller than the FLAC ({len(body)} >= {original})"
        return f"FLAC {original} B -> Opus {len(body)} B"

    @check("serves synced lyrics from a .lrc file next to the song")
    def _():
        flac = next(s for s in nd.songs if s["title"] == "First")
        status, _, body = nd.subsonic("getLyricsBySongId", id=flac["id"])
        assert status == 200, f"getLyricsBySongId -> {status}"
        lyrics = json.loads(body)["subsonic-response"].get("lyricsList", {}).get("structuredLyrics", [])
        assert lyrics, f"no lyrics in the answer: {body[:200]!r}"
        assert lyrics[0].get("synced") is True and len(lyrics[0]["line"]) == 3, lyrics[0]

    @check("rate-limits wrong passwords out of the box (no setting needed)")
    def _():
        codes = []
        for _ in range(25):
            try:
                status, _, _ = http("POST", nd.base + "/auth/login",
                                    {"username": nd.user, "password": "wrong"})
            except OSError:
                status = 0  # the connection was dropped: also a refusal, not a pass
            codes.append(status)
        assert 429 in codes, f"no 429 after 25 wrong attempts: {sorted(set(codes))}"
        first = codes.index(429) + 1
        assert first <= 10, f"the limit only starts at attempt {first}"
        return f"429 from attempt {first} (Navidrome default: 5 per 20 s)"

    @check("writes scheduled database backups and keeps only the newest ones")
    def _():
        backups = nd.work / "data" / "backup"

        def enough():
            files = list(backups.glob("*")) if backups.exists() else []
            return files if len(files) >= 2 else None

        wait_until(enough, 30, "two scheduled backups")
        time.sleep(7)  # a few more cycles: the count must stay at the limit
        files = sorted(backups.glob("*"))
        assert 1 <= len(files) <= 2, f"BACKUP_COUNT=2 but {len(files)} files: {[f.name for f in files]}"
        return f"{len(files)} kept: {files[-1].name}"

    @check("`navidrome backup create` works while the server runs")
    def _():
        target = nd.work / "manual-backup"
        target.mkdir(exist_ok=True)
        done = nd.cli("backup", "create", "-d", str(target))
        assert done.returncode == 0, (done.stdout + done.stderr)[-300:]
        assert any(target.iterdir()), "no file was written"

    @check("never writes into the music folder (so a read-only mount is enough)")
    def _():
        # A full scan, a stream, a transcode and lyrics have all happened by now.
        after = tree_state(music)
        assert after == before, "the music folder changed: " + str(
            set(after.items()) ^ set(before.items()))[:300]
        return f"{len(after)} files untouched"


def make_person_song(ffmpeg: str, folder: Path, artist: str, album: str, title: str,
                     hertz: int) -> None:
    target = folder / artist / f"{album} (2024)" / f"01 - {title}.mp3"
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"sine=frequency={hertz}:duration=3", "-metadata", f"title={title}",
         "-metadata", f"artist={artist}", "-metadata", f"album_artist={artist}",
         "-metadata", f"album={album}", "-metadata", "track=1", "-metadata", "date=2024",
         "-c:a", "libmp3lame", "-b:a", "128k", str(target)],
        check=True)


def proxy_checks(binary: str, ffmpeg: str, root: Path) -> None:
    """Behind a proxy or the Funnel sidecar every guest arrives from one address (docs/33, T5). What Navidrome 0.64 does."""
    SECRET = "X-Encore-9f3c1a77d02b44e1aa05c3d8e7b6f219"
    CLIENT_A, CLIENT_B = "198.51.100.7", "203.0.113.9"  # documentation addresses (RFC 5737)

    def start(name: str, extra: dict) -> Navidrome:
        work = root / name
        (work / "music").mkdir(parents=True, exist_ok=True)
        (work / "data").mkdir(parents=True, exist_ok=True)
        make_tracks(ffmpeg, work / "music")
        nd = Navidrome(binary, str(Path(ffmpeg).parent), work)
        nd.env.update(extra)
        nd.start()
        status, _, body = http("POST", nd.base + "/auth/createAdmin", {"username": nd.user, "password": nd.password})
        assert status == 200, f"createAdmin -> {status} {body[:120]!r}"
        return nd

    def ok(nd: Navidrome, **kw) -> bool:
        status, _, body = nd.subsonic_as(nd.user, nd.password, "ping", **kw)
        return status == 200 and json.loads(body)["subsonic-response"]["status"] == "ok"

    def guess(nd: Navidrome, how_many: int, headers_for) -> None:
        for i in range(how_many):
            nd.subsonic_as(nd.user, "wrong-guess", "ping", headers=headers_for(i))

    def via(client: str) -> dict:
        return {"X-Forwarded-For": client}

    nd = None
    try:
        @check("[proxy] the trap exists: with no trusted proxy one stranger's guesses block everyone behind it")
        def _():
            nonlocal nd
            nd = start("proxy-plain", {})
            guess(nd, 10, lambda i: via(CLIENT_A))
            assert not ok(nd, headers=via(CLIENT_B)), "guest B was served: Navidrome now sees real client addresses, rethink"
            nd.stop()
            return "guest B's right password is refused after guest A's wrong guesses (all share one address)"

        @check("[proxy] a trusted proxy gives every client its own limit: B is served while A is blocked")
        def _():
            nonlocal nd
            nd = start("proxy-trusted", {"ND_EXTAUTH_TRUSTEDSOURCES": "127.0.0.0/8", "ND_EXTAUTH_USERHEADER": SECRET})
            guess(nd, 10, lambda i: via(CLIENT_A))
            assert ok(nd, headers=via(CLIENT_B)), "guest B was refused although only guest A guessed"
            assert not ok(nd, headers=via(CLIENT_A)), "guest A was served while blocked: the limiter is not per client"
            return "B is served, A is held back"

        @check("[proxy] a made-up leading X-Forwarded-For value does not give a stranger a fresh limit")
        def _():
            stranger = "192.0.2.55"  # a client nobody has used yet in this run
            guess(nd, 10, lambda i: {"X-Forwarded-For": f"10.9.9.{i}, {stranger}"})  # a different made-up prefix every time
            assert not ok(nd, headers=via(stranger)),                 "the stranger got a fresh limit for every made-up prefix: the limit followed the spoofed value"
            assert ok(nd, headers=via(CLIENT_B)), "an unrelated client was blocked as well"
            return "the address the proxy appended is the one that counts"

        @check("[proxy] a peer outside the trusted range cannot choose its own address")
        def _():
            nd.stop()
            nd2 = start("proxy-untrusted", {"ND_EXTAUTH_TRUSTEDSOURCES": "10.0.0.0/8", "ND_EXTAUTH_USERHEADER": SECRET})
            try:
                guess(nd2, 10, lambda i: via(CLIENT_A))
                assert not ok(nd2, headers=via(CLIENT_B)), "an untrusted peer's X-Forwarded-For was believed"
            finally:
                nd2.stop()
            return "forwarded addresses from an untrusted peer are ignored"

        @check("[proxy] the danger exists: trusting a proxy with the default user header logs anyone in with no password")
        def _():
            danger = start("proxy-danger", {"ND_EXTAUTH_TRUSTEDSOURCES": "127.0.0.0/8"})
            try:
                status, _, body = http("GET", danger.base + "/rest/ping?v=1.16.1&c=check&f=json",
                                       headers={"Remote-User": danger.user})
                answer = json.loads(body)["subsonic-response"]
                assert answer["status"] == "ok", f"the header did not log in ({answer}): Navidrome changed, rethink the guard"
            finally:
                danger.stop()
            return "Remote-User: <name> was enough, which is why the helper refuses that setting"

        @check("[proxy] a secret header name closes it: the old and a guessed header do nothing, normal login works")
        def _():
            secure = start("proxy-secure", {"ND_EXTAUTH_TRUSTEDSOURCES": "127.0.0.0/8", "ND_EXTAUTH_USERHEADER": SECRET})
            try:
                for header in ("Remote-User", "X-Encore-00000000000000000000000000000000"):
                    status, _, body = http("GET", secure.base + "/rest/ping?v=1.16.1&c=check&f=json",
                                           headers={header: secure.user})
                    assert json.loads(body)["subsonic-response"]["status"] == "failed", f"{header} logged someone in"
                assert ok(secure), "the normal password login stopped working"
            finally:
                secure.stop()
            return "only the secret header name counts, and nobody can guess it"
    finally:
        if nd is not None:
            nd.stop()


def people_service_checks(binary: str, ffmpeg: str, root: Path) -> None:
    """The invite flow end to end against the REAL Navidrome (docs/35): the service's HTTP layer, its token check and the account tool."""
    service = HERE.parent.parent / "encore-people"
    sys.path.insert(0, str(service))
    try:
        from encore_people.activity import Activity
        from encore_people.invites import Invites
        from encore_people.navidrome import Navidrome as PeopleNavidrome
        from encore_people.provision import NavidromeProvisioner
        from encore_people.server import Api, Settings
    except ImportError as error:
        record("SKIP", "[people-service] invites against the real music server", f"cannot import the service: {error}")
        return

    work = root / "people-service-run"
    music = work / "music"
    (work / "data").mkdir(parents=True, exist_ok=True)
    make_tracks(ffmpeg, music / "_shared")
    nd = Navidrome(binary, str(Path(ffmpeg).parent), work, music_folder=music / "_shared")
    nd.env["ND_BACKUP_SCHEDULE"] = ""
    state: dict = {}

    def token(user: str, password: str) -> str:
        salt = "p" + hashlib.md5(os.urandom(6)).hexdigest()[:8]
        return urllib.parse.urlencode({"u": user, "t": hashlib.md5((password + salt).encode()).hexdigest(), "s": salt})

    def call(method: str, path: str, *, auth: tuple[str, str] | None = None, body: object | None = None):
        target = path + ("?" + token(*auth) if auth else "")
        data = json.dumps(body).encode() if body is not None else b""
        response = state["api"].handle(method, target, {}, data, "198.51.100.7")
        return response.status, (json.loads(response.body) if response.body[:1] in (b"{", b"[") else response.body)

    def libs_of(name: str) -> list[str]:
        user = next(u for u in state["admin"].users() if u["userName"] == name)
        return sorted(lib["name"] for lib in state["admin"].call("GET", f"/api/user/{user['id']}")["libraries"])

    try:
        @check("[people-service] starts; an administrator makes an invite, an ordinary person cannot")
        def _():
            nd.start()
            status, _, body = http("POST", nd.base + "/auth/createAdmin", {"username": nd.user, "password": nd.password})
            assert status == 200, f"createAdmin -> {status} {body[:120]!r}"
            state["admin"] = encore_user.Admin(nd.base, nd.user, nd.password)
            sara = encore_user.add_person(state["admin"], "sara", music_root=str(music), create_dir=str(music))
            state["sara_pw"] = sara["password"]
            provisioner = NavidromeProvisioner(nd.base, nd.user, nd.password, music, music_root=str(music), account_tool=encore_user)
            invites = Invites(work / "people.db", provisioner=provisioner)
            state["invites"] = invites
            state["api"] = Api(invites=invites, activity=Activity(work / "sharing.json"),
                               navidrome=PeopleNavidrome(nd.base), settings=Settings("https://music.example.ts.net", "Test server"))
            status, made = call("POST", "/api/invites", auth=("sara", state["sara_pw"]))
            assert status == 403, f"an ordinary person made an invite: {status} {made}"
            status, made = call("POST", "/api/invites", auth=(nd.user, nd.password))
            assert status == 201, f"the administrator could not: {status} {made}"
            state["code"] = made["url"].rsplit("/", 1)[-1]
            state["sara_before"] = libs_of("sara")
            return "the music server decides who is an administrator"

        @check("[people-service] a friend redeems the invite: own library plus the shared one, and the audit stays clean")
        def _():
            status, answer = call("POST", f"/join/{state['code']}/redeem", body={"username": "ben", "password": "ben-long-password"})
            assert status == 201, f"redeem -> {status} {answer}"
            assert libs_of("ben") == sorted(["ben", "Music Library"]), \
                f"the friend must have exactly their own library and the shared one, has {libs_of('ben')}"
            assert (music / "ben").is_dir(), "the friend's own folder must exist"
            findings = encore_user.audit(state["admin"])
            assert findings == [], f"the audit found: {findings}"
            status, _, body = nd.subsonic_as("ben", "ben-long-password", "ping")
            assert status == 200 and json.loads(body)["subsonic-response"]["status"] == "ok", "the friend cannot sign in"
            _, _, found = nd.subsonic_as("ben", "ben-long-password", "search3", query="", songCount="50")
            titles = sorted(s["title"] for s in json.loads(found)["subsonic-response"].get("searchResult3", {}).get("song", []))
            assert titles == ["First", "Second", "Third"], f"the friend should see the shared songs only, saw {titles}"
            return f"libraries {libs_of('ben')}, sees only the shared songs"

        @check("[people-service] the same invitation cannot be used twice")
        def _():
            status, _ = call("POST", f"/join/{state['code']}/redeem", body={"username": "tom", "password": "tom-long-password"})
            assert status == 404, f"second use -> {status}"
            assert not any(u["userName"] == "tom" for u in state["admin"].users()), "a second account was made"
            return "refused, and nothing was made"

        @check("[people-service] a taken name is refused and the existing person's account is left exactly as it was")
        def _():
            _, made = call("POST", "/api/invites", auth=(nd.user, nd.password))
            code = made["url"].rsplit("/", 1)[-1]
            for taken in ("sara", nd.user):
                status, answer = call("POST", f"/join/{code}/redeem", body={"username": taken, "password": "some-long-password"})
                assert status == 400 and "taken" in answer["error"], f"{taken}: {status} {answer}"
            assert libs_of("sara") == state["sara_before"], "an existing person's libraries were changed by a stranger's invitation"
            status, _ = call("GET", f"/join/{code}/info")
            assert status == 200, "a refused name must not use up the invitation"
            state["code2"] = code
            return "sara's libraries unchanged; the invitation is still open"

        @check("[people-service] a folder that already exists under the chosen name is not taken over")
        def _():
            (music / "ghost").mkdir(exist_ok=True)
            (music / "ghost" / "private.txt").write_text("not for anyone else", encoding="utf-8")
            status, answer = call("POST", f"/join/{state['code2']}/redeem", body={"username": "ghost", "password": "some-long-password"})
            assert status == 400 and "taken" in answer["error"], f"{status} {answer}"
            assert not any(u["userName"] == "ghost" for u in state["admin"].users())
            return "refused"
    finally:
        nd.stop()
        if "invites" in state:
            state["invites"].close()


def multi_user_checks(binary: str, ffmpeg: str, root: Path) -> None:
    """Several people on one server: layout _shared + one folder per person."""
    work = root / "people-run"
    music = work / "music"
    shared = music / "_shared"
    (work / "data").mkdir(parents=True, exist_ok=True)
    make_tracks(ffmpeg, shared)
    make_person_song(ffmpeg, music / "sara", "Sara Artist", "Her Album", "Hers", 550)
    make_person_song(ffmpeg, music / "ben", "Ben Artist", "His Album", "His", 660)
    nd = Navidrome(binary, str(Path(ffmpeg).parent), work, music_folder=shared)
    nd.env["ND_BACKUP_SCHEDULE"] = ""  # off: also proves an empty schedule is a valid choice
    state: dict = {}

    def titles(user: str, password: str) -> list[str]:
        _, _, body = nd.subsonic_as(user, password, "search3", query="", songCount="50")
        found = json.loads(body)["subsonic-response"].get("searchResult3", {}).get("song", [])
        return sorted(song["title"] for song in found)

    try:
        @check("[people] starts with the shared folder as the first library")
        def _():
            nd.start()
            status, _, body = http("POST", nd.base + "/auth/createAdmin",
                                   {"username": nd.user, "password": nd.password})
            assert status == 200, f"createAdmin -> {status} {body[:120]!r}"
            state["admin"] = encore_user.Admin(nd.base, nd.user, nd.password)
            libs = state["admin"].libraries()
            assert len(libs) == 1 and encore_user.is_shared(libs[0]["path"]), libs
            assert libs[0]["defaultNewUsers"] is True, "expected Navidrome's default"
            return f"library 1 = {libs[0]['path']}"

        @check("[options] an empty backup schedule switches the automatic backup off")
        def _():
            log = (work / "navidrome.log").read_text(errors="replace")
            assert "Periodic backup is DISABLED" in log, "Navidrome did not say it is disabled"
            backups = work / "data" / "backup"
            assert not backups.exists() or not any(backups.iterdir()), "a backup was written anyway"
            return "no backup folder content; the person decides"

        @check("[people] the trap exists: a plain new account is handed the shared library")
        def _():
            admin = state["admin"]
            made = admin.call("POST", "/api/user", {
                "userName": "trap", "name": "Trap", "email": "", "password": "trap-pass-1",
                "isAdmin": False})
            got = [lib["id"] for lib in admin.call("GET", f"/api/user/{made['id']}")["libraries"]]
            admin.call("DELETE", f"/api/user/{made['id']}")
            assert got, "a new account has no library by default: Navidrome changed, rethink the tool"
            return "so the tool must set the list explicitly (and does)"

        @check("[people] add_person gives each person only their own library and the shared one")
        def _():
            admin = state["admin"]
            for name in ("sara", "ben"):
                result = encore_user.add_person(admin, name, music_root=str(music))
                state[name] = result["password"]
                assert len(result["libraries"]) == 2 and name in result["libraries"], result
            nd.subsonic("startScan", fullScan="true")
            wait_until(lambda: (len(titles(nd.user, nd.password)) == 5) or None, 60,
                       "all five songs to be scanned")
            return "sara and ben created"

        @check("[people] the admin sees everything; each person sees shared + own, never the other's")
        def _():
            assert set(titles(nd.user, nd.password)) == {"First", "Second", "Third", "Hers", "His"}
            assert set(titles("sara", state["sara"])) == {"First", "Second", "Third", "Hers"}
            assert set(titles("ben", state["ben"])) == {"First", "Second", "Third", "His"}
            return "search3 is filtered by person"

        @check("[people] artists and music folders are separated too, not only songs")
        def _():
            for name, own, other in (("sara", "Sara Artist", "Ben Artist"),
                                     ("ben", "Ben Artist", "Sara Artist")):
                _, _, body = nd.subsonic_as(name, state[name], "getArtists")
                indexes = json.loads(body)["subsonic-response"]["artists"].get("index", [])
                names = {a["name"] for ix in indexes for a in ix["artist"]}
                assert own in names and other not in names, (name, names)
                _, _, body = nd.subsonic_as(name, state[name], "getMusicFolders")
                folders = json.loads(body)["subsonic-response"]["musicFolders"]["musicFolder"]
                assert len(folders) == 2, (name, folders)

        @check("[people] a person cannot stream or open another person's song by its id")
        def _():
            _, _, body = nd.subsonic("search3", query="His", songCount="5")
            his = next(s for s in json.loads(body)["subsonic-response"]["searchResult3"]["song"]
                       if s["title"] == "His")
            status, _, answer = nd.subsonic_as("sara", state["sara"], "stream", id=his["id"])
            assert not answer.startswith((b"ID3", b"\xff\xfb")), "sara received ben's audio"
            _, _, body = nd.subsonic_as("sara", state["sara"], "getSong", id=his["id"])
            reply = json.loads(body)["subsonic-response"]
            assert reply["status"] == "failed", reply
            return f"error {reply['error']['code']}: {reply['error']['message']}"

        @check("[people] playlists and likes belong to the person who made them")
        def _():
            _, _, body = nd.subsonic_as("sara", state["sara"], "search3", query="Hers", songCount="3")
            hers = json.loads(body)["subsonic-response"]["searchResult3"]["song"][0]["id"]
            status, _, _ = nd.subsonic_as("sara", state["sara"], "createPlaylist",
                                          name="Sara mix", songId=hers)
            assert status == 200
            nd.subsonic_as("sara", state["sara"], "star", id=hers)

            def playlists(user, password):
                _, _, body = nd.subsonic_as(user, password, "getPlaylists")
                return [pl["name"] for pl in
                        json.loads(body)["subsonic-response"].get("playlists", {}).get("playlist", [])]

            def starred(user, password):
                _, _, body = nd.subsonic_as(user, password, "getStarred2")
                return [s["title"] for s in
                        json.loads(body)["subsonic-response"].get("starred2", {}).get("song", [])]

            assert "Sara mix" in playlists("sara", state["sara"])
            assert "Sara mix" not in playlists("ben", state["ben"]), "ben can list sara's playlist"
            assert starred("sara", state["sara"]) == ["Hers"]
            assert starred("ben", state["ben"]) == [], "ben sees sara's like"

        @check("[people] the same artist in two private libraries stays separate")
        def _():
            make_person_song(ffmpeg, music / "sara", "Common Band", "Sara Disc", "SaraTune", 700)
            make_person_song(ffmpeg, music / "ben", "Common Band", "Ben Disc", "BenTune", 800)
            nd.subsonic("startScan", fullScan="true")
            wait_until(lambda: ("SaraTune" in titles(nd.user, nd.password)
                                and "BenTune" in titles(nd.user, nd.password)) or None,
                       60, "both Common Band songs to be scanned")

            def albums_of_common_band(user, password):
                _, _, body = nd.subsonic_as(user, password, "getArtists")
                indexes = json.loads(body)["subsonic-response"]["artists"].get("index", [])
                artist = next((a for ix in indexes for a in ix["artist"] if a["name"] == "Common Band"), None)
                assert artist, f"{user} does not see the artist at all"
                _, _, body = nd.subsonic_as(user, password, "getArtist", id=artist["id"])
                return sorted(al["name"] for al in
                              json.loads(body)["subsonic-response"]["artist"].get("album", []))

            assert albums_of_common_band("sara", state["sara"]) == ["Sara Disc"],                 albums_of_common_band("sara", state["sara"])
            assert albums_of_common_band("ben", state["ben"]) == ["Ben Disc"],                 albums_of_common_band("ben", state["ben"])
            assert "BenTune" not in titles("sara", state["sara"])
            return "one artist name, two audiences, no leak"

        @check("[people] a person can be mapped to a folder with another name")
        def _():
            make_person_song(ffmpeg, music / "legacy", "Old Artist", "Old Album", "OldSong", 900)
            admin = state["admin"]
            result = encore_user.add_person(admin, "alex", music_root=str(music), folder="legacy")
            state["alex"] = result["password"]
            nd.subsonic("startScan", fullScan="true")
            wait_until(lambda: ("OldSong" in titles("alex", state["alex"])) or None, 60,
                       "alex to see the legacy folder")
            assert "OldSong" not in titles("sara", state["sara"]), "sara can see alex's folder"
            assert encore_user.audit(admin) == [], encore_user.audit(admin)
            return "alex -> folder legacy, audit clean"

        @check("[people] a person can have a second, writable library for what they add (alex-added); nobody else sees it")
        def _():
            admin = state["admin"]
            make_person_song(ffmpeg, music / "alex-added", "Added Artist", "Added Album", "AddedSong", 1000)
            result = encore_user.add_person(admin, "alex", music_root=str(music), folder="legacy",
                                            extra_folders=["alex-added"], create_dir=str(music))
            assert sorted(result["libraries"]) == sorted(["alex", "alex-added", "Music Library"]), result["libraries"]
            nd.subsonic("startScan", fullScan="true")
            wait_until(lambda: ("AddedSong" in titles("alex", state["alex"])) or None, 60, "alex to see alex-added")
            assert "OldSong" in titles("alex", state["alex"]), "the first library was lost"
            assert "AddedSong" not in titles("sara", state["sara"]), "sara can see alex's added music"
            assert "AddedSong" not in titles("ben", state["ben"]), "ben can see alex's added music"
            assert encore_user.audit(admin) == [], encore_user.audit(admin)
            return "alex sees both of his libraries, nobody else sees the second; audit clean"

        @check("[people] an extra folder must be clearly the person's own, and one person's name never passes for another's")
        def _():
            admin = state["admin"]
            try:
                encore_user.add_person(admin, "alex", music_root=str(music), folder="legacy", extra_folders=["sara"])
            except encore_user.ToolError as error:
                assert "alex-" in str(error), str(error)
            else:
                raise AssertionError("an extra folder that is not called alex-something was accepted")
            # sara must not pass for "sara-b" or the reverse: a person called sara-b has a library named sara-b
            encore_user.add_person(admin, "sara-b", music_root=str(music), create_dir=str(music))
            sara = next(u for u in admin.users() if u["userName"] == "sara")
            sara_b_lib = next(lib for lib in admin.libraries() if lib["name"] == "sara-b")
            mine = [lib["id"] for lib in admin.call("GET", f"/api/user/{sara['id']}")["libraries"]]
            admin.call("PUT", f"/api/user/{sara['id']}/library", {"libraryIds": sorted(set(mine + [sara_b_lib["id"]]))})
            found = encore_user.audit(admin)
            assert any("sara can see library 'sara-b'" in line for line in found), f"sara-b's library passed for sara's: {found}"
            encore_user.add_person(admin, "sara", music_root=str(music), password="ignored")
            assert encore_user.audit(admin) == [], "running add again did not repair it"
            return "refused, and a person named sara-b is not mistaken for sara's extra library"

        @check("[people] the audit is clean, then catches a person given too much")
        def _():
            admin = state["admin"]
            assert encore_user.audit(admin) == [], encore_user.audit(admin)
            sara = next(u for u in admin.users() if u["userName"] == "sara")
            every = [lib["id"] for lib in admin.libraries()]
            admin.call("PUT", f"/api/user/{sara['id']}/library", {"libraryIds": every})
            found = encore_user.audit(admin)
            assert any("sara can see library" in line for line in found), found
            encore_user.add_person(admin, "sara", music_root=str(music), password="ignored")
            assert encore_user.audit(admin) == [], "running add again did not repair it"
            return "found: " + found[0]

        @check("[people] a library inside another one is refused (it would leak music)")
        def _():
            admin = state["admin"]
            try:
                encore_user.add_person(admin, "inner", music_root=str(music / "_shared"))
            except encore_user.ToolError as error:
                assert "contain each other" in str(error), error
                return "refused with a plain-words reason"
            raise AssertionError("a library nested in the shared one was created")

        @check("[people] only the shared library is still handed to new accounts")
        def _():
            admin = state["admin"]
            defaults = [lib["name"] for lib in admin.libraries() if lib["defaultNewUsers"]]
            assert len(defaults) == 1 and defaults[0] == "Music Library", defaults
            return "only the shared library is a default"
    finally:
        nd.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--navidrome", help="path to the navidrome binary")
    parser.add_argument("--ffmpeg", help="path to ffmpeg (default: from PATH)")
    parser.add_argument("--work", help="folder for the throw-away run (default: a temp folder)")
    parser.add_argument("--keep", action="store_true", help="keep the work folder")
    args = parser.parse_args()

    static_checks()
    setup_checks()

    if not args.navidrome:
        record("SKIP", "runtime checks against a real Navidrome", "pass --navidrome PATH")
    else:
        ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
        if not ffmpeg:
            record("FAIL", "ffmpeg is needed to generate the songs and to transcode", "pass --ffmpeg PATH")
        else:
            root = Path(args.work or tempfile.mkdtemp(prefix="encore-reference-"))
            work = root / "run"
            (work / "music").mkdir(parents=True, exist_ok=True)
            (work / "data").mkdir(parents=True, exist_ok=True)
            make_tracks(ffmpeg, work / "music")
            nd = Navidrome(args.navidrome, str(Path(ffmpeg).parent), work)
            try:
                runtime_checks(nd, ffmpeg)
            finally:
                nd.stop()
            try:
                proxy_checks(args.navidrome, ffmpeg, root)
                people_service_checks(args.navidrome, ffmpeg, root)
                multi_user_checks(args.navidrome, ffmpeg, root)
            finally:
                if not args.keep:
                    shutil.rmtree(root, ignore_errors=True)

    failed = [r for r in results if r[0] == "FAIL"]
    skipped = [r for r in results if r[0] == "SKIP"]
    print(f"\n{len(results) - len(failed) - len(skipped)} passed, {len(failed)} failed, "
          f"{len(skipped)} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
