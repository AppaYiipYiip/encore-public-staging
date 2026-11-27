"""The helper's root session (P3-25, slice 6a; docs/36 section 3): what the admin pages may ask of the computer, run for real.

`encore helper-session` reads ONE line from a socket as root and answers with a few lines. The proofs here are the ones the threat model names:

* **A table of hostile request lines, each refused, and nothing ran** (no `docker` call, no `tailscale`, no `systemd-run`, no file made by an injected command): an empty line, a token
  alone, an extra word, a wrong token of the right shape, a token too short or too long, an action in the wrong case, every shell metacharacter, a lookalike letter, an over-long line, a
  second request after a line break, the actions that are deliberately NOT on the list (`restore.apply`, `update.apply`, ...), no token configured, a client that sends nothing.
* The seven actions, answered in `result:`, `item:`, `done:` and `failed:` lines, never more than one line each, never a control character.
* `away.on` **never installs Tailscale and never signs in** (a host without it, or signed out, is refused with the sentence that sends the Host to the terminal).
* **The helper's own backups have a pool of their own**: any number of requests leaves the nightly and the terminal's backups where they are.
* A key that the accounts were not locked with makes `restart` refuse in words instead of asking.
* The helper's own record of every request (a job file), refused ones included.
* `encore helper install --files-only`: the units, the tmpfiles line, the compose override, the token once; and `dc` reads the override only when it exists.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from encore_server.backup import new_key
from tests.test_deploy_flow import KEY_A, Install, msys
from tests.test_deploy_scripts import BASH

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

TOKEN = "T" * 8 + "abcdefgh" * 4  # 40 characters of the token alphabet
ANSWER_LINE = re.compile(r"^(result|item|done|failed): ")

FAKE_TAILSCALE = r"""#!/usr/bin/env bash
echo "tailscale $*" >>"$TS_LOG"
case "$1" in
    status) [ "${TS_STATE:-ready}" = ready ] && exit 0 || exit 1 ;;
    funnel)
        if [ "${2:-}" = status ]; then exit 0; fi
        # a tailnet without Funnel prints a link and waits for a person
        if [ "${TS_HANG:-}" = 1 ]; then echo "To enable Funnel visit https://login.tailscale.com/f/funnel"; sleep 30; fi
        exit 0 ;;
    *) exit 0 ;;
esac
"""


class Rig:
    def __init__(self, tmp_path: Path, token: str | None = TOKEN) -> None:
        self.install = Install(tmp_path, KEY_A, "helper")
        self.tmp = tmp_path
        self.bin = self.install.bin
        self.ts_log = tmp_path / "ts.log"
        self.run_log = tmp_path / "systemd-run.log"
        self.syslog = tmp_path / "syslog.log"
        self.jobs = tmp_path / "jobs"
        for path in (self.ts_log, self.run_log, self.syslog):
            path.write_text("", encoding="utf-8")
        self._stub("logger", f'#!/usr/bin/env bash\necho "$*" >>"{msys(self.syslog)}"\n')
        self._stub("flock", '#!/usr/bin/env bash\n[ "${FAKE_FLOCK_BUSY:-}" = 1 ] && exit 1\nexit 0\n')
        self._stub("systemd-run", f'#!/usr/bin/env bash\necho "$*" >>"{msys(self.run_log)}"\n')
        self._stub("tailscale", FAKE_TAILSCALE)
        if token is not None:
            self.install.set_env(self.install.env + f"ENCORE_HELPER_TOKEN={token}\n")

    def _stub(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(body, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def remove(self, name: str) -> None:
        (self.bin / name).unlink()

    def env(self, **more: str) -> dict[str, str]:
        return {
            "ENCORE_HELPER_LOCK": msys(self.tmp / "helper.lock"),
            "ENCORE_JOBS_DIR": msys(self.jobs),
            "ENCORE_HELPER_EVERY_S": "0",
            "TS_LOG": msys(self.ts_log),
            **more,
        }

    def ask(self, line: str, **env: str) -> subprocess.CompletedProcess[str]:
        return self.install.encore("helper-session", stdin=line.encode("utf-8"), extra_env=self.env(**env))

    def nothing_ran(self) -> bool:
        return (
            self.install.calls() == []
            and self.ts_log.read_text(encoding="utf-8") == ""
            and self.run_log.read_text(encoding="utf-8") == ""
        )

    def jobs_of(self) -> list[dict[str, object]]:
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.jobs.glob("*.json"))] if self.jobs.exists() else []


def lines_of(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [ln for ln in result.stdout.splitlines()]


REFUSED = "failed: That request was refused."


# ---------------------------------------------------------------------------------------------------------------------- the hostile lines


def hostile(pwned: str) -> list[tuple[str, str]]:
    return [
        ("empty line", "\n"),
        ("only a newline and spaces", "   \n"),
        ("a token alone", f"{TOKEN}\n"),
        ("an action alone", "status\n"),
        ("an extra word", f"{TOKEN} status extra\n"),
        ("an id nobody takes", f"{TOKEN} backup.make x\n"),
        ("a wrong token of the right shape", f"{'W' * 40} status\n"),
        ("a token one character short", f"{TOKEN[:-1]} status\n"),
        ("a token one character long", f"{TOKEN}x status\n"),
        ("a token too short to be one", "short status\n"),
        ("a token of 200 characters", f"{'T' * 200} status\n"),
        ("the action in capitals", f"{TOKEN} STATUS\n"),
        ("a dot at the end", f"{TOKEN} status.\n"),
        ("a dot at the start", f"{TOKEN} .status\n"),
        ("two dots", f"{TOKEN} backup..make\n"),
        ("a semicolon", f"{TOKEN} status;touch {pwned}\n"),
        ("a command substitution", f"{TOKEN} $(touch {pwned})\n"),
        ("a backtick", f"{TOKEN} `touch {pwned}`\n"),
        ("a pipe", f"{TOKEN} status|touch {pwned}\n"),
        ("an ampersand", f"{TOKEN} status&touch {pwned}\n"),
        ("a path", f"{TOKEN} ../../bin/sh\n"),
        ("a redirect", f"{TOKEN} status>{pwned}\n"),
        ("two spaces", f"{TOKEN}  status\n"),
        ("a tab between", f"{TOKEN}\tstatus\n"),
        ("a tab after", f"{TOKEN} status\t\n"),
        ("a carriage return", f"{TOKEN} status\r\n"),
        ("a lookalike letter (Cyrillic s)", f"{TOKEN} ѕtatus\n"),
        ("a line of 300 characters", f"{TOKEN} " + "a" * 300 + "\n"),
        ("a line of exactly 257 characters", ("T" * 40 + " " + "a" * 216) + "\n"),
        ("the restore the list leaves out", f"{TOKEN} restore.apply\n"),
        ("the update the list leaves out", f"{TOKEN} update.apply\n"),
        ("another update word", f"{TOKEN} update.check\n"),
        ("a verify the list leaves out", f"{TOKEN} backup.verify\n"),
        ("an add-on action nobody has", f"{TOKEN} addon.enable\n"),
        ("a shell", f"{TOKEN} shell\n"),
        ("exec", f"{TOKEN} exec\n"),
        ("a bare word of the list's family", f"{TOKEN} backup\n"),
        ("a bare away", f"{TOKEN} away\n"),
    ]


def test_every_hostile_line_is_refused_and_nothing_runs(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    pwned = tmp_path / "pwned"
    for name, line in hostile(msys(pwned)):
        result = rig.ask(line)
        assert result.stdout.strip() == REFUSED, (name, result.stdout, result.stderr)
        assert result.returncode == 0, name
        assert rig.nothing_ran(), name
        assert not pwned.exists(), f"{name}: an injected command ran"
    assert {j["result"] for j in rig.jobs_of()} == {"refused"}, "every one of them is in the helper's own record"
    assert len(rig.jobs_of()) == len(hostile("x"))
    assert "refused" in rig.syslog.read_text(encoding="utf-8")


def test_a_second_request_after_a_line_break_is_never_read(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    result = rig.ask(f"{TOKEN} status\n{TOKEN} backup.make\n")
    assert [ln for ln in lines_of(result) if ln.startswith("done")] == ["done: ok"], "one request, one answer"
    assert not (rig.install.root / "backups" / "helper").exists() and rig.install.calls().count("docker:run") == 0


def test_without_a_token_in_the_settings_nothing_is_ever_accepted(tmp_path: Path) -> None:
    for token in (None, "", "short", "S" * 31):
        folder = tmp_path / f"t{len(token) if token is not None else 0}-{token is None}"
        folder.mkdir()
        rig = Rig(folder, token)
        assert rig.ask(f"{TOKEN} status\n").stdout.strip() == REFUSED
        assert rig.ask(" status\n").stdout.strip() == REFUSED
        assert rig.nothing_ran()


def test_a_client_that_sends_nothing_is_not_waited_for_for_ever(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    env = {"PATH": f"{msys(rig.bin)}:/usr/bin:/bin", "ENCORE_DIR": msys(rig.install.root), **rig.env()}
    assert BASH is not None
    process = subprocess.Popen(
        [BASH, str(Path(__file__).resolve().parent.parent / "deploy" / "encore"), "helper-session"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        out, _ = process.communicate(timeout=30)  # stdin stays open and silent: the session must give up by itself (5 seconds)
    finally:
        process.kill()
    assert out.strip() == REFUSED


# ---------------------------------------------------------------------------------------------------------------------- the seven actions


def test_status_answers_in_lines_and_the_helper_keeps_its_own_record(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    result = rig.ask(f"{TOKEN} status\n")
    assert result.returncode == 0, result.stderr
    out = lines_of(result)
    assert out[0] == "result: helper=1" and out[-1] == "done: ok"
    keys = {ln.split(": ", 1)[1].split("=", 1)[0] for ln in out if ln.startswith("result: ")}
    assert keys == {"helper", "encoreServer", "musicServer", "away", "tailscale", "lastBackup"}
    assert all(ANSWER_LINE.match(ln) and len(ln) <= 310 and not re.search(r"[\x00-\x1f\x1b]", ln) for ln in out)
    assert [j["action"] for j in rig.jobs_of()] == ["status"] and rig.jobs_of()[0]["result"] == "ok"
    assert "status ok" in rig.syslog.read_text(encoding="utf-8")


def test_the_list_shows_the_computers_backups_and_the_admin_pools_apart(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    backups = rig.install.root / "backups"
    (backups / "helper").mkdir(parents=True)
    (backups / "encore-backup-20261101-030000.tar.gz.age").write_bytes(b"x" * 10)
    (backups / "encore-backup-20261102-030000.tar.gz").write_bytes(b"y" * 20)
    (backups / "helper" / "encore-backup-20261103-120000.tar.gz.age").write_bytes(b"z" * 30)
    (backups / "notes.txt").write_text("not a backup", encoding="utf-8")
    items = [ln.split(" ") for ln in lines_of(rig.ask(f"{TOKEN} backup.list\n")) if ln.startswith("item: ")]
    assert sorted((i[1], i[2], i[3], i[5]) for i in items) == [
        ("admin", "encore-backup-20261103-120000.tar.gz.age", "30", "locked"),
        ("computer", "encore-backup-20261101-030000.tar.gz.age", "10", "locked"),
        ("computer", "encore-backup-20261102-030000.tar.gz", "20", "plain"),
    ]


def test_a_backup_asked_for_by_a_page_goes_to_a_pool_of_its_own_and_can_never_rotate_the_others_out(tmp_path: Path) -> None:
    """The review's point: keep-the-newest-7 let seven requests erase every good backup. The helper's own copies live elsewhere, three at most."""
    rig = Rig(tmp_path)
    install = rig.install
    public, _ = new_key()
    install.lock_with(public)
    assert install.encore("backup", "--quiet").returncode == 0
    nightly = sorted((install.root / "backups").glob("encore-backup-*"))
    assert len(nightly) == 1
    oldest = nightly[0]
    stamp = oldest.stat().st_mtime
    for n in range(6):
        result = rig.ask(f"{TOKEN} backup.make\n")
        assert "done: A backup was made." in lines_of(result), (n, result.stdout, result.stderr)
        time.sleep(1.1)  # a backup's name is its second: each request needs its own
    assert sorted((install.root / "backups").glob("encore-backup-*")) == [oldest] and oldest.stat().st_mtime == stamp
    assert len(list((install.root / "backups" / "helper").glob("encore-backup-*"))) <= 3, "the helper's pool is the newest three"


def test_a_second_backup_inside_ten_minutes_is_refused_in_words(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    first = rig.ask(f"{TOKEN} backup.make\n", ENCORE_HELPER_EVERY_S="600")
    assert "done: A backup was made." in lines_of(first), first.stdout + first.stderr
    again = rig.ask(f"{TOKEN} backup.make\n", ENCORE_HELPER_EVERY_S="600")
    failed = [ln for ln in lines_of(again) if ln.startswith("failed: ")]
    assert failed and "Wait ten minutes" in failed[0], again.stdout
    assert len(list((rig.install.root / "backups" / "helper").glob("encore-backup-*"))) == 1


def test_only_one_change_at_a_time(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    busy = rig.ask(f"{TOKEN} backup.make\n", FAKE_FLOCK_BUSY="1")
    assert "failed: Another request is running. Try again in a minute." in lines_of(busy)
    assert not (rig.install.root / "backups" / "helper").exists(), "it did not start"
    assert rig.jobs_of()[-1]["result"] == "busy"
    # reads do not take the lock
    assert "done: ok" in lines_of(rig.ask(f"{TOKEN} status\n", FAKE_FLOCK_BUSY="1"))


@pytest.mark.parametrize("state", ["missing", "signedout"])
def test_the_away_address_is_never_set_up_by_a_page_and_no_link_is_ever_returned(tmp_path: Path, state: str) -> None:
    """The review's point: `tailscale up` prints a sign-in link that joins the computer to the network of whoever completes it. A page may only flip the Funnel of a Tailscale that is set up."""
    rig = Rig(tmp_path)
    if state == "missing":
        rig.remove("tailscale")
    result = rig.ask(f"{TOKEN} away.on\n", TS_STATE="signedout")
    assert "failed: Set up the away address once at the computer: sudo encore funnel on" in lines_of(result), (
        result.stdout + result.stderr
    )
    assert rig.ts_log.read_text(encoding="utf-8") == "tailscale status\n" or state == "missing", (
        "it asked only whether Tailscale is signed in"
    )
    assert "login" not in result.stdout.lower() and "http" not in result.stdout.lower(), "no link comes back"
    assert "tailscale up" not in rig.ts_log.read_text(encoding="utf-8")
    assert "install.sh" not in " ".join(rig.install.calls()), "nothing is downloaded and run"


def test_the_away_address_is_switched_on_for_a_tailscale_that_is_set_up(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    result = rig.ask(f"{TOKEN} away.on\n", TS_STATE="ready")
    assert "done: The away address is on." in lines_of(result), result.stdout + result.stderr
    calls = rig.ts_log.read_text(encoding="utf-8")
    assert "tailscale funnel --bg --https=443 4533" in calls and "tailscale up" not in calls
    status = rig.ask(f"{TOKEN} away.status\n", TS_STATE="ready")
    assert "result: tailscale=ready" in lines_of(status) and lines_of(status)[-1] == "done: ok"
    assert "result: tailscale=signedout" in lines_of(rig.ask(f"{TOKEN} away.status\n", TS_STATE="signedout"))


def test_restart_answers_before_it_acts_and_is_a_detached_unit(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    result = rig.ask(f"{TOKEN} restart\n")
    assert lines_of(result)[0].startswith("done: Restarting.")
    ran = rig.run_log.read_text(encoding="utf-8")
    assert "--no-block" in ran and ran.strip().endswith("restart") and "encore-helper-restart-" in ran


def test_restart_refuses_in_words_when_the_accounts_key_is_not_the_one_they_were_locked_with(tmp_path: Path) -> None:
    """`encore restart` guards the key; behind the helper nothing could answer a question, so it must say so and stop, never wait."""
    rig = Rig(tmp_path)
    rig.install.mark.parent.mkdir(parents=True, exist_ok=True)
    rig.install.mark.write_text("0" * 64 + "\n", encoding="utf-8")  # a mark made with another key
    result = rig.ask(f"{TOKEN} restart\n")
    failed = [ln for ln in lines_of(result) if ln.startswith("failed: ")]
    assert failed and "key" in failed[0].lower() and len(failed[0]) <= 310, result.stdout
    assert rig.run_log.read_text(encoding="utf-8") == "", "nothing was restarted"
    assert rig.jobs_of()[-1]["result"] == "failed"


# ---------------------------------------------------------------------------------------------------------------------- the install


def test_helper_install_writes_the_units_the_directory_mount_and_the_token_once(tmp_path: Path) -> None:
    rig = Rig(tmp_path, token=None)
    install = rig.install
    units, tmpfiles = tmp_path / "units", tmp_path / "tmpfiles"
    install.set_env(install.env + "ENCORE_HELPER_GID=1234\n")
    env = {"ENCORE_UNIT_DIR": msys(units), "ENCORE_TMPFILES_DIR": msys(tmpfiles)}
    result = install.encore("helper", "install", "--files-only", extra_env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    socket_unit = (units / "encore-helper.socket").read_text(encoding="utf-8")
    for line in (
        "ListenStream=/run/encore/helper.sock",
        "SocketMode=0660",
        "SocketUser=root",
        "SocketGroup=encore-helper",
        "Accept=yes",
        "MaxConnections=8",
    ):
        assert line in socket_unit, line
    service = (units / "encore-helper@.service").read_text(encoding="utf-8")
    assert "StandardInput=socket" in service and "StandardOutput=socket" in service and "RuntimeMaxSec=300" in service
    assert re.search(r"ExecStart=\S+ helper-session", service)
    assert (tmpfiles / "encore-helper.conf").read_text(encoding="utf-8") == "d /run/encore 0750 root encore-helper -\n"
    override = (install.root / "compose.helper.yaml").read_text(encoding="utf-8")
    assert "- /run/encore:/run/encore" in override and "/run/encore/helper.sock" not in override.split("volumes:")[1], (
        "the DIRECTORY is mounted, never the socket file"
    )
    assert 'group_add:\n      - "${ENCORE_HELPER_GID}"' in override and "ENCORE_HELPER_TOKEN: ${ENCORE_HELPER_TOKEN}" in override
    token = re.search(r"^ENCORE_HELPER_TOKEN=(\S+)$", install.env, re.M)
    assert token is not None and re.fullmatch(r"[A-Za-z0-9]{32,128}", token.group(1)), "a token the session accepts"
    assert token.group(1) not in override, "no secret in the override"
    again = install.encore("helper", "install", "--files-only", extra_env=env)
    assert again.returncode == 0 and re.findall(r"^ENCORE_HELPER_TOKEN=(\S+)$", install.env, re.M) == [token.group(1)], (
        "run again, the token is kept"
    )


def test_dc_reads_the_override_only_when_it_exists(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    install = rig.install
    install.encore("stop")
    before = [c for c in install.calls() if c.startswith("docker:compose")]
    assert before and all("-f" not in c.split() for c in before), "an install without the override runs exactly as before"
    (install.root / "compose.helper.yaml").write_text("services: {}\n", encoding="utf-8")
    install.log.write_text("", encoding="utf-8")
    install.encore("stop")
    after = [c for c in install.calls() if c.startswith("docker:compose")]
    assert after and all("-f" in c.split() for c in after), after


def test_the_session_has_no_eval_no_sh_c_and_no_action_takes_an_argument() -> None:
    """The threat model's row 5 as a build failure: the session is a `case`, and nothing in it may run a string as code."""
    script = (Path(__file__).resolve().parent.parent / "deploy" / "encore").read_text(encoding="utf-8")
    start = (
        script.index("# The helper (docs/36 section 3)")
        if "# The helper (docs/36 section 3)" in script
        else script.index("HELPER_LOCK=")
    )
    end = script.index("# `encore secure`: the two keys of this install")
    session = script[start:end]
    assert not re.search(r"\beval\b", session) and "sh -c" not in session and "bash -c" not in session
    assert "cmd_helper_session() {" in session
    body = session[session.index("cmd_helper_session() {") : session.index("# `away.on` as the helper asks it")]
    assert re.search(r"\^\(\[A-Za-z0-9_-\]\{32,128\}\)\\ \(\[a-z\]\+\(\\\.\[a-z\]\+\)\?\)\$", body), (
        "the grammar is TOKEN SPACE ACTION and nothing else"
    )
    for word in ("status", "backup.list", "away.status", "backup.make", "away.on", "away.off", "restart"):
        assert re.search(rf"^\s+{re.escape(word)}\)", body, re.M) or word in body, word
    assert "restore" not in body and "update" not in body, "deliberately not on the list"


# ---------------------------------------------------------------------------------------------------------------------- what the review of the code found


def test_a_client_that_hangs_up_cannot_erase_the_record_or_stop_the_act(tmp_path: Path) -> None:
    """Review: the answer was written first and the record after, under `set -e`; a client that closed its end made the first write fail and the session end, so the backup happened and
    no record existed. Now the record is written before the act, a failed write is never fatal, and SIGPIPE is ignored."""
    rig = Rig(tmp_path)
    env = {
        "PATH": f"{msys(rig.bin)}:/usr/bin:/bin",
        "ENCORE_DIR": msys(rig.install.root),
        "FAKE_PYTHON": msys(rig.bin / "fakepython"),
        "FAKE_IMAGE_DIR": msys(rig.install.image),
        "FAKE_LOG": msys(rig.install.log),
        "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
        "PYTHONUTF8": "1",
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        **rig.env(),
    }
    assert BASH is not None
    process = subprocess.Popen(
        [BASH, str(Path(__file__).resolve().parent.parent / "deploy" / "encore"), "helper-session"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdout.close()  # the client has hung up
    process.stdin.write(f"{TOKEN} backup.make\n".encode())
    process.stdin.close()
    process.wait(timeout=120)
    assert len(list((rig.install.root / "backups" / "helper").glob("encore-backup-*"))) == 1, "the act happened"
    assert [j["result"] for j in rig.jobs_of()] == ["started", "ok"], "and the helper's own record says so, before and after"


def test_every_change_is_recorded_before_it_is_done(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.ask(f"{TOKEN} backup.make\n")
    assert [(j["action"], j["result"]) for j in rig.jobs_of()] == [("backup.make", "started"), ("backup.make", "ok")]


def test_the_away_address_recreates_the_server_only_after_the_answer_and_by_a_detached_unit(tmp_path: Path) -> None:
    """Review: `tell_server_away` ran `dc up -d`, which replaces the Encore container that is waiting for the answer. In helper mode it only leaves a mark; the session recreates after answering."""
    rig = Rig(tmp_path)
    result = rig.ask(f"{TOKEN} away.on\n", TS_STATE="ready")
    assert "done: The away address is on." in lines_of(result), result.stdout + result.stderr
    assert not any(" up" in c for c in rig.install.calls() if c.startswith("docker:compose")), (
        "the session did not recreate the container itself"
    )
    ran = rig.run_log.read_text(encoding="utf-8")
    assert "encore-helper-apply-" in ran and ran.strip().endswith("apply"), "a detached unit does it, after"
    assert not (rig.install.root / ".helper-recreate").exists(), "the mark is consumed"
    assert [j["result"] for j in rig.jobs_of()][-2:] == ["started", "ok"]


def test_a_tailscale_that_waits_for_a_person_does_not_hold_the_helper(tmp_path: Path) -> None:
    """Review: a tailnet without Funnel prints a link and waits; behind the helper that would hold the lock until the unit's time limit."""
    rig = Rig(tmp_path)
    started = time.monotonic()
    result = rig.ask(f"{TOKEN} away.on\n", TS_STATE="ready", TS_HANG="1", ENCORE_HELPER_TS_TIMEOUT="1")
    assert time.monotonic() - started < 25, "it did not wait for the person"
    failed = [ln for ln in lines_of(result) if ln.startswith("failed: ")]
    assert failed and "Tailscale would not turn Funnel on" in failed[0], result.stdout
    assert "login.tailscale.com/f/funnel" not in result.stdout, "the link tailscale itself printed never reaches the caller"
    assert not (rig.install.root / ".helper-recreate").exists()
    assert rig.jobs_of()[-1]["result"] == "failed"


def test_the_session_never_writes_where_the_container_can_write() -> None:
    """Review: root truncated a lock inside the directory the container could write (a planted symlink would have made it truncate a host file), and made a temporary file in `data/`
    before renaming it. The container runs as root (no USER in the image), so this was a way to damage the host."""
    script = (Path(__file__).resolve().parent.parent / "deploy" / "encore").read_text(encoding="utf-8")
    assert 'HELPER_LOCK="${ENCORE_HELPER_LOCK:-/run/lock/encore-helper.lock}"' in script, "the lock is root's alone"
    assert "/run/encore/helper.lock" not in script
    assert 'mktemp "$DIR/.host-status-XXXXXX"' in script and 'mktemp "$DIR/data/' not in script, (
        "temporary files are made in root's own folder and renamed into data/"
    )
    override = script[script.index('cat >"$DIR/compose.helper.yaml"') :]
    assert "- /run/encore:/run/encore:ro\nCOMPOSE" in override, "the socket's directory is read-only inside the container"
    session = script[script.index("cmd_helper_session() {") : script.index("# `away.on` as the helper asks it")]
    assert "trap '' PIPE" in session and "exec 0</dev/null" in session
    assert session.index("exec 0</dev/null") < session.index('case "$action" in'), (
        "nothing the session starts can read the client's bytes"
    )


def test_the_helper_session_is_dispatched_before_anything_else_runs_as_root() -> None:
    script = (Path(__file__).resolve().parent.parent / "deploy" / "encore").read_text(encoding="utf-8")
    assert script.index('if [ "${1:-}" = helper-session ]; then') < script.index("tidy_setup_code || true\n\ncase")


def test_the_installers_own_dc_reads_the_helpers_override_too() -> None:
    """Review: any recreate that skips the override silently drops the socket mount, the group and the token."""
    install = (Path(__file__).resolve().parent.parent / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert '-f "$DIR/compose.helper.yaml"' in install
    assert len(re.findall(r"docker compose (?!version)", install)) == 2, (
        "only dc itself calls docker compose (once with the override, once without)"
    )
