"""The computer's half of the first run in the browser (P3-06 slice 5a; docs/36 section 2): the installer makes the setup code and says where to type it, the `encore` command shows the
link while the owner is still to be made and takes the code out of the settings file when the server says the owner exists, and the headless door (`--owner`) is still there.

The shell is run for real (the same `bash` the tests of the other deploy scripts use), with the made-up install the flow tests use; nothing here needs Docker.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from encore_server import setup_code
from tests.test_deploy_flow import KEY_A, Install
from tests.test_deploy_scripts import BASH, DEPLOY

INSTALL = (DEPLOY / "install.sh").read_text(encoding="utf-8")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def function(name: str) -> str:
    """The text of one function of `install.sh` (from `name() {` to the closing brace at the start of a line)."""
    match = re.search(rf"^{name}\(\) \{{.*?^\}}\n", INSTALL, re.S | re.M)
    assert match is not None, name
    return match.group(0)


def run(script: str) -> subprocess.CompletedProcess[str]:
    assert BASH is not None
    return subprocess.run([BASH, "-c", script], capture_output=True, text=True, check=False, timeout=60)


# ---------------------------------------------------------------------------------------------------------------------- the code the installer makes


def test_the_installer_makes_a_code_the_server_accepts_and_never_the_same_twice() -> None:
    script = "set -Eeuo pipefail\n" + function("make_setup_code") + "\nfor _ in $(seq 1 60); do make_setup_code; echo; done"
    result = run(script)
    assert result.returncode == 0, result.stderr
    codes = result.stdout.split()
    assert len(codes) == 60 and all(re.fullmatch(r"[A-Z2-9]{3}-[A-Z2-9]{3}", c) for c in codes), codes[:5]
    assert all(setup_code.well_formed(c) and not set(c) & set("0O1IL") for c in codes)
    assert len(set(codes)) > 55, "a code is made fresh from the system's randomness"


def test_the_settings_file_gets_a_code_once_and_keeps_it(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("ENCORE_PORT=4533\nENCORE_PASSWORD_KEY=k\n", encoding="utf-8", newline="\n")
    script = (
        f'set -Eeuo pipefail; DIR="{tmp_path.as_posix()}"; die() {{ echo "DIED: $*" >&2; exit 9; }}\n'
        'env_value() { grep -E "^$1=" "$DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- || true; }\n'
        + function("make_setup_code")
        + function("ensure_setup_code")
        + '\nensure_setup_code; first="$(env_value ENCORE_SETUP_CODE)"; ensure_setup_code; second="$(env_value ENCORE_SETUP_CODE)"\n'
        'echo "$first $second"'
    )
    result = run(script)
    assert result.returncode == 0, result.stderr
    first, second = result.stdout.split()
    assert first == second and setup_code.well_formed(first), "a link already shown still works after a second run"
    lines = env.read_text(encoding="utf-8").splitlines()
    assert (
        lines[:2] == ["ENCORE_PORT=4533", "ENCORE_PASSWORD_KEY=k"]
        and sum(1 for ln in lines if ln.startswith("ENCORE_SETUP_CODE=")) == 1
    )
    assert any(ln.startswith("# Only until the owner") for ln in lines), "the line says what it is"


def test_the_installer_has_both_doors_and_says_where_to_go() -> None:
    """Text of the script (it cannot be run whole without Docker): the browser door is the default, `--owner` keeps the old one, and the screen shows the link and the code."""
    assert 'if [ -n "$OWNER" ]; then NEED_OWNER=1; else BROWSER_OWNER=1; fi' in INSTALL
    assert 'if [ "$NEED_OWNER" = 1 ]; then : >"$DIR/.setup-pending"; fi' in INSTALL, (
        "the old marker is only for the door where the installer makes the account"
    )
    assert "/setup?code=${SETUP_CODE}" in INSTALL and "type this setup code" in INSTALL
    assert 'if [ "$NEED_OWNER" = 1 ]; then ask_owner; fi' in INSTALL, (
        "nobody is asked for a name and password at the terminal any more"
    )
    assert INSTALL.count("ENCORE_SETUP_CODE") >= 3
    assert '[ ! -e "$DIR/data/setup-complete" ]' in INSTALL, (
        "a re-run shows the link again only while the owner is still to be made"
    )
    compose = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    assert "ENCORE_SETUP_CODE: ${ENCORE_SETUP_CODE:-}" in compose, "the server is given the code (or nothing)"


# ---------------------------------------------------------------------------------------------------------------------- the encore command


def test_status_shows_the_link_while_the_owner_is_to_be_made_and_not_after(tmp_path: Path) -> None:
    install = Install(tmp_path, KEY_A, "link")
    install.set_env(install.env + "# Only until the owner's account is made in the browser: x\nENCORE_SETUP_CODE=7KQ-4MZ\n")
    shown = install.encore("status").stdout
    assert re.search(
        r"Your account is not made yet\. Open this link in a browser on your home network: +http://\S+:4533/setup\?code=7KQ-4MZ",
        shown,
    ), shown
    (install.root / "data" / "setup-complete").write_text("done\n", encoding="utf-8")
    after = install.encore("status").stdout
    assert "7KQ-4MZ" not in after and "Your account is not made yet" not in after


def test_status_says_nothing_about_setup_when_there_never_was_a_code(tmp_path: Path) -> None:
    install = Install(tmp_path, KEY_A, "nocode")
    assert "Your account is not made yet" not in install.encore("status").stdout


def test_when_the_server_says_the_owner_exists_the_code_leaves_the_settings_file_and_nothing_else_does(tmp_path: Path) -> None:
    install = Install(tmp_path, KEY_A, "tidy")
    install.set_env(
        install.env
        + "# Only until the owner's account is made in the browser: the setup pages need it, the encore command takes it out afterwards.\nENCORE_SETUP_CODE=7KQ-4MZ\nENCORE_HOME_URL=http://10.0.0.5:4533\n"
    )
    before = install.env.splitlines()
    install.encore("status")
    assert "ENCORE_SETUP_CODE" in install.env, "nothing is taken out while the owner is still to be made"
    (install.root / "data" / "setup-complete").write_text("done\n", encoding="utf-8")
    result = install.encore("status")
    assert result.returncode == 0, result.stderr
    after = install.env.splitlines()
    assert "ENCORE_SETUP_CODE" not in install.env and "Only until the owner" not in install.env
    assert after == [
        ln for ln in before if not ln.startswith("ENCORE_SETUP_CODE=") and not ln.startswith("# Only until the owner")
    ]
    assert "ENCORE_PASSWORD_KEY=" + KEY_A in after, "every other line, the keys above all, is kept exactly"
    assert not list(install.root.glob(".env.*")), "no copy of the settings file is left behind"
    install.encore("status")
    assert install.env.splitlines() == after, "a second time changes nothing"


def test_a_settings_file_that_cannot_be_copied_is_never_emptied(tmp_path: Path) -> None:
    """The only line left would be the code: the copy would be empty, so nothing is done (a settings file holds the keys of the install)."""
    install = Install(tmp_path, KEY_A, "only")
    install.set_env("ENCORE_SETUP_CODE=7KQ-4MZ\n")
    (install.root / "data" / "setup-complete").write_text("done\n", encoding="utf-8")
    install.encore("status")
    assert install.env == "ENCORE_SETUP_CODE=7KQ-4MZ\n"
    assert not list(install.root.glob(".env.*"))
