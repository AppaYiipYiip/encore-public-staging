"""The shell scripts that install and look after a server (docs/tasks P3-05): the parts that only read text are tested here as plain functions,
so they do not wait for a real Tailscale or a real machine. The scripts as a whole are proved on clean machines (docs/evidence/c01, c02)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def find_bash() -> str | None:
    """A bash that works: ENCORE_BASH if set, else the first on the path that runs (on Windows the first one can be the WSL stub)."""
    for candidate in (os.environ.get("ENCORE_BASH"), shutil.which("bash")):
        if not candidate:
            continue
        try:
            probe = subprocess.run([candidate, "-c", "echo ok"], capture_output=True, text=True, check=False, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and probe.stdout.strip() == "ok":
            return candidate
    return None


BASH = find_bash()

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

# What `tailscale funnel status` prints (its documented text), for a computer that has nothing, one site of ours, and one that
# already serves another service on 443 with ours next to it on 8443.
NOTHING = "No serve config\n"
OURS_ON_443 = """# Funnel on:
#     - https://encore-home.tail1234.ts.net

https://encore-home.tail1234.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:4533

"""
OTHER_ON_443 = """# Funnel on:
#     - https://box.tail1234.ts.net

https://box.tail1234.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:3000

"""
BOTH = """# Funnel on:
#     - https://box.tail1234.ts.net
#     - https://box.tail1234.ts.net:8443

https://box.tail1234.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:3000

https://box.tail1234.ts.net:8443 (Funnel on)
|-- / proxy http://127.0.0.1:4533

"""
TAILNET_ONLY = """https://box.tail1234.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:3000
"""


def helpers() -> str:
    """The text of the pure `funnel_*` functions of the `encore` script."""
    script = (DEPLOY / "encore").read_text(encoding="utf-8")
    start = script.index("funnel_port_in_use() {")
    end = script.index("\nfunnel_address() {", start)
    return script[start:end]


def run(function_call: str, status: str) -> tuple[int, str]:
    assert BASH is not None
    result = subprocess.run(
        [BASH, "-c", f"{helpers()}\n{function_call}"], input=status, capture_output=True, text=True, check=False, timeout=30
    )
    return result.returncode, result.stdout.strip()


@pytest.mark.parametrize(
    ("status", "port", "used"),
    [
        (NOTHING, "443", False),
        (OURS_ON_443, "443", True),
        (OURS_ON_443, "8443", False),
        (OTHER_ON_443, "443", True),
        (OTHER_ON_443, "8443", False),
        (BOTH, "443", True),
        (BOTH, "8443", True),
        (BOTH, "10000", False),
        (TAILNET_ONLY, "443", True),
    ],
)
def test_which_public_ports_are_taken(status: str, port: str, used: bool) -> None:
    code, _ = run(f"funnel_port_in_use {port}", status)
    assert (code == 0) is used


def test_the_comment_lines_at_the_top_do_not_count_as_a_site() -> None:
    """The "# Funnel on:" list repeats every address; only the lines that start with https:// are sites."""
    code, _ = run("funnel_port_in_use 8443", "# Funnel on:\n#     - https://box.tail1234.ts.net:8443\n")
    assert code != 0


@pytest.mark.parametrize(
    ("status", "address"),
    [
        (NOTHING, ""),
        (OURS_ON_443, "https://encore-home.tail1234.ts.net"),
        (OTHER_ON_443, ""),
        (BOTH, "https://box.tail1234.ts.net:8443"),
    ],
)
def test_the_address_that_points_at_encore(status: str, address: str) -> None:
    code, out = run("funnel_address_for 4533", status)
    assert code == 0
    assert out == address


def test_a_site_of_something_else_is_not_taken_for_encore() -> None:
    """With two sites, the address given is the one whose proxy is Encore's port, not simply the first."""
    _, out = run("funnel_address_for 3000", BOTH)
    assert out == "https://box.tail1234.ts.net"


@pytest.mark.parametrize(("status", "count"), [(NOTHING, "0"), (OURS_ON_443, "1"), (BOTH, "2")])
def test_how_many_sites_there_are(status: str, count: str) -> None:
    _, out = run("funnel_site_count", status)
    assert out == count


@pytest.mark.parametrize("name", ["install.sh", "encore"])
def test_the_scripts_parse(name: str) -> None:
    assert BASH is not None
    result = subprocess.run([BASH, "-n", (DEPLOY / name).as_posix()], capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr


def test_the_help_text_lists_every_command() -> None:
    """The header comment is what `encore help` prints (lines 2 to 14): each command the script dispatches on is in it."""
    script = (DEPLOY / "encore").read_text(encoding="utf-8")
    header = "\n".join(script.splitlines()[1:14])
    dispatched = set(re.findall(r"^\s{4}(\w+)\)", script.split('case "${1:-help}" in')[1], flags=re.M))
    for command in dispatched - {"help", "version", "start", "stop", "restart", "logs"}:
        assert f"encore {command}" in header, command
