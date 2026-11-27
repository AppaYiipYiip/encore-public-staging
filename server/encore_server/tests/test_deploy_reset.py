"""`encore reset-password` and `encore recovery-key` (P3-16): the shell half, run for real with a stand-in for the server's `op` command.

The operations themselves are proved in `test_reset_password.py` against the real database. Here the script's own part: it asks the server what to ask, gets the new password and the key to the server on
standard input from a private file (never on a command line, never in the environment), refuses what it can refuse before bothering the server, shows a new recovery key once and nowhere else, and
leaves no file behind.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.test_deploy_flow import KEY_A, Install, msys
from tests.test_deploy_scripts import BASH

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

NEW_KEY = "ABCD-EFGH-JKMN-PQRS-TUVW"

STUB = r"""#!/usr/bin/env bash
# The server's `op` command, as the script meets it through `docker compose exec`: what it was asked and what came on standard input go to a log; the answer is canned.
args=("$@")
for i in "${!args[@]}"; do [ "${args[$i]}" = op ] && break; done
op=("${args[@]:$((i + 1))}")
echo "ARGS: ${op[*]}" >>"$FAKE_OPLOG"
case "${op[*]}" in
    *--info*)
        [ "${FAKE_NOISE:-}" = 1 ] && echo "WARN: a compose or Python warning on standard error" >&2
        if [ "${op[1]}" = nobody ]; then echo 'There is nobody called "nobody" on this server.' >&2; exit 1; fi
        echo "$FAKE_STATE"
        ;;
    reset-password*)
        input="$(cat)"
        echo "STDIN: $input" >>"$FAKE_OPLOG"
        [ "${FAKE_NOISE:-}" = 1 ] && echo "WARN: a warning before the answer" >&2
        if [ "${FAKE_REFUSE:-}" = 1 ]; then echo "That recovery key is not right." >&2; exit 1; fi
        echo "name=${op[1]}"; echo "devicesEnded=2"; echo "usedKey=false"
        if [ "$FAKE_STATE" != member ]; then echo "recovery-key=ABCD-EFGH-JKMN-PQRS-TUVW"; fi
        ;;
    "recovery-key --check")
        [ "${FAKE_DOWN:-}" = 1 ] && exit 1
        [ -n "${FAKE_KEYLESS:-}" ] && echo "$FAKE_KEYLESS"
        ;;
    recovery-key*)
        if [ "${FAKE_REFUSE:-}" = 1 ]; then echo "Only an owner has a recovery key." >&2; exit 1; fi
        echo "name=riley"; echo "recovery-key=ABCD-EFGH-JKMN-PQRS-TUVW"
        ;;
esac
"""


def rig(tmp_path: Path, state: str = "member") -> tuple[Install, dict[str, str], Path]:
    install = Install(tmp_path, KEY_A, "reset")
    stub = install.bin / "fake-op"
    stub.write_text(STUB, encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    oplog = tmp_path / "op.log"
    oplog.write_text("", encoding="utf-8")
    env = {"FAKE_EXEC": msys(stub), "FAKE_OPLOG": msys(oplog), "FAKE_STATE": state}
    return install, env, oplog


def write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8", newline="\n")
    return str(path)


def test_a_members_password_goes_to_the_server_on_standard_input_and_nowhere_else(tmp_path: Path) -> None:
    install, env, oplog = rig(tmp_path)
    pw = write(tmp_path / "pw", "a brand new password\nignored second line\n")
    result = install.encore("reset-password", "nina", "--password-file", pw, extra_env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    log = oplog.read_text(encoding="utf-8")
    assert "ARGS: reset-password nina --info" in log and "ARGS: reset-password nina\n" in log
    assert 'STDIN: {"password":"a brand new password","recoveryKey":""}' in log
    assert "a brand new password" not in " ".join(install.calls()), "never on a command line"
    assert "The password of nina is changed" in result.stdout and "2 signed-in device(s) were signed out" in result.stdout
    assert "Recovery key" not in result.stdout and "ABCD" not in result.stdout, "a member has no key"
    assert "ten minutes" in result.stdout, "the one thing that is not at once is said"
    assert "a brand new password" not in result.stdout + result.stderr


def test_an_owner_with_a_key_is_asked_for_it_and_shown_the_new_one_once(tmp_path: Path) -> None:
    install, env, oplog = rig(tmp_path, "owner-with-key")
    pw = write(tmp_path / "pw", "another long password\n")
    keyfile = write(tmp_path / "key", "wxyz-wxyz-wxyz-wxyz-wxyz\n")
    result = install.encore("reset-password", "riley", "--password-file", pw, "--recovery-key-file", keyfile, extra_env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"recoveryKey":"wxyz-wxyz-wxyz-wxyz-wxyz"' in oplog.read_text(encoding="utf-8")
    assert result.stdout.count(NEW_KEY) == 1, "the new key is shown exactly once"
    assert "shown once" in result.stdout and "sudo encore recovery-key" in result.stdout
    assert NEW_KEY not in oplog.read_text(encoding="utf-8").split("STDIN:")[1], "and was never sent to the server"


def test_the_server_refusing_is_said_in_its_own_sentence_and_nothing_is_shown(tmp_path: Path) -> None:
    install, env, _ = rig(tmp_path, "owner-with-key")
    pw = write(tmp_path / "pw", "another long password\n")
    result = install.encore("reset-password", "riley", "--password-file", pw, extra_env={**env, "FAKE_REFUSE": "1"})
    assert result.returncode == 1 and "That recovery key is not right." in result.stderr
    assert NEW_KEY not in result.stdout + result.stderr and "is changed" not in result.stdout


def test_an_unknown_name_is_told_before_anything_is_asked(tmp_path: Path) -> None:
    install, env, oplog = rig(tmp_path)
    pw = write(tmp_path / "pw", "a brand new password\n")
    result = install.encore("reset-password", "nobody", "--password-file", pw, extra_env=env)
    assert result.returncode == 1 and 'There is nobody called "nobody" on this server.' in result.stderr
    assert "STDIN" not in oplog.read_text(encoding="utf-8"), "no password was ever sent"


@pytest.mark.parametrize(
    ("args", "words"),
    [
        ((), "Use:  encore reset-password NAME"),
        (("nina", "extra"), "Use:  encore reset-password NAME"),
        (("nina", "--nonsense"), "Unknown option --nonsense"),
        (("nina", "--password-file", "/no/such/file"), "cannot be read"),
        (("nina",), "run it in a terminal"),
    ],
)
def test_what_the_script_can_refuse_itself_it_refuses_before_the_server(
    tmp_path: Path, args: tuple[str, ...], words: str
) -> None:
    install, env, oplog = rig(tmp_path)
    result = install.encore("reset-password", *args, extra_env=env)
    assert result.returncode == 1 and words in result.stderr, result.stderr
    assert "STDIN" not in oplog.read_text(encoding="utf-8")


def test_a_password_with_a_control_character_is_refused_here(tmp_path: Path) -> None:
    install, env, oplog = rig(tmp_path)
    pw = write(tmp_path / "pw", "a brand\tnew password\n")
    result = install.encore("reset-password", "nina", "--password-file", pw, extra_env=env)
    assert result.returncode == 1 and "control characters" in result.stderr
    assert "STDIN" not in oplog.read_text(encoding="utf-8")


def test_a_password_with_quotes_and_backslashes_arrives_whole(tmp_path: Path) -> None:
    install, env, oplog = rig(tmp_path)
    pw = write(tmp_path / "pw", 'pa"ss\\word with "quotes"\n')
    assert install.encore("reset-password", "nina", "--password-file", pw, extra_env=env).returncode == 0
    assert r'STDIN: {"password":"pa\"ss\\word with \"quotes\"","recoveryKey":""}' in oplog.read_text(encoding="utf-8")


def test_a_new_recovery_key_is_shown_once_for_the_owner(tmp_path: Path) -> None:
    install, env, oplog = rig(tmp_path, "owner")
    result = install.encore("recovery-key", extra_env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A new recovery key is made for riley; the old one no longer works" in result.stdout
    assert result.stdout.count(NEW_KEY) == 1
    assert "ARGS: recovery-key" in oplog.read_text(encoding="utf-8")
    refused = install.encore("recovery-key", "nina", extra_env={**env, "FAKE_REFUSE": "1"})
    assert refused.returncode == 1 and "Only an owner has a recovery key." in refused.stderr and NEW_KEY not in refused.stdout


def test_the_help_and_the_dispatcher_know_both_commands(tmp_path: Path) -> None:
    install, _, _ = rig(tmp_path)
    helptext = install.encore("help").stdout
    assert re.search(r"encore reset-password NAME", helptext) and re.search(r"encore recovery-key \[NAME\]", helptext)


def test_a_warning_on_standard_error_does_not_change_what_the_script_asks_or_says(tmp_path: Path) -> None:
    """Found in review: `--info` was read with stderr merged into the value it is compared with, so any warning line made an owner with a key look like nobody: the key was never asked and the audit line said "without"."""
    install, env, oplog = rig(tmp_path, "owner-with-key")
    pw = write(tmp_path / "pw", "another long password\n")
    keyfile = write(tmp_path / "key", "wxyz-wxyz-wxyz-wxyz-wxyz\n")
    noisy = {**env, "FAKE_NOISE": "1"}
    with_key = install.encore("reset-password", "riley", "--password-file", pw, "--recovery-key-file", keyfile, extra_env=noisy)
    assert with_key.returncode == 0 and '"recoveryKey":"wxyz-wxyz-wxyz-wxyz-wxyz"' in oplog.read_text(encoding="utf-8")
    assert "Going on without" not in with_key.stdout
    # an owner with a key and no key given: said in words, and still recognised through the noise
    without = install.encore("reset-password", "riley", "--password-file", pw, extra_env=noisy)
    assert (
        without.returncode == 0 and "Going on without the recovery key (none was given); the audit log says so." in without.stdout
    )
    # the sentence of a refusal is the LAST line the server said, not a warning that came first
    refused = install.encore("reset-password", "riley", "--password-file", pw, extra_env={**noisy, "FAKE_REFUSE": "1"})
    assert refused.returncode == 1 and "That recovery key is not right." in refused.stderr and "WARN" not in refused.stderr
    key_made = install.encore("recovery-key", extra_env={**noisy, "FAKE_STATE": "owner"})
    assert key_made.returncode == 0 and key_made.stdout.count(NEW_KEY) == 1


def test_status_tells_an_owner_without_a_recovery_key_how_to_make_one(tmp_path: Path) -> None:
    """An owner made before keys existed, or by the headless door, has no way back from a forgotten password but root's own: `encore status` says so, once, in words."""
    install, env, _ = rig(tmp_path)
    shown = install.encore("status", extra_env={**env, "FAKE_KEYLESS": "riley"}).stdout
    assert "No recovery key yet for: riley. Make one now with:  sudo encore recovery-key" in shown, shown
    assert "No recovery key yet" not in install.encore("status", extra_env=env).stdout, "an owner who has a key is not nagged"
    assert "No recovery key yet" not in install.encore("status", extra_env={**env, "FAKE_DOWN": "1"}).stdout, (
        "silent when the server does not answer"
    )
    two = install.encore("status", extra_env={**env, "FAKE_KEYLESS": "riley" + chr(10) + "sara"}).stdout
    assert "No recovery key yet for: riley sara." in two
