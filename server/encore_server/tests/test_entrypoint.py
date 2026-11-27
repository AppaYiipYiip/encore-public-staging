"""The container's entrypoint (P3-25): which groups the server keeps when it drops root.

Found by the real-install job (27 Nov 2026), invisible to every other test: the entrypoint started the server with `setpriv --init-groups`, which resets the supplementary groups, so the one
group that `compose.helper.yaml`'s `group_add` gave the container (the helper socket's group, mode 660) was dropped and the running server got `Permission denied` on the socket, while
`docker compose exec` (root, which ignores permissions) worked. The entrypoint now keeps exactly that group, and nothing else (not root's group 0), and only when it is a number.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.test_deploy_flow import msys
from tests.test_deploy_scripts import BASH

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

ENTRYPOINT = Path(__file__).resolve().parent.parent / "entrypoint.sh"


def run(tmp_path: Path, uid: str, gid: str | None) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "setpriv.log"
    log.write_text("", encoding="utf-8")
    stubs = {
        "id": f"#!/usr/bin/env bash\necho {uid}\n",
        "stat": "#!/usr/bin/env bash\necho 1000\n",
        "chown": "#!/usr/bin/env bash\nexit 0\n",
        "setpriv": f'#!/usr/bin/env bash\necho "$*" >>"{msys(log)}"\n',
    }
    for name, body in stubs.items():
        path = bin_dir / name
        path.write_text(body, encoding="utf-8", newline="\n")
        path.chmod(0o755)
    env = {"PATH": f"{msys(bin_dir)}:/usr/bin:/bin"}
    if gid is not None:
        env["ENCORE_HELPER_GID"] = gid
    assert BASH is not None
    done = subprocess.run(
        [BASH, str(ENTRYPOINT), "the-server", "--flag"], capture_output=True, text=True, check=False, timeout=30, env=env
    )
    return done, log.read_text(encoding="utf-8").splitlines()


def test_without_a_helper_the_server_keeps_no_group(tmp_path: Path) -> None:
    done, calls = run(tmp_path, "0", None)
    assert done.returncode == 0, done.stderr
    assert calls == ["--reuid=1000 --regid=1000 --clear-groups the-server --flag"]


def test_with_a_helper_the_server_keeps_that_one_group_and_no_other(tmp_path: Path) -> None:
    done, calls = run(tmp_path, "0", "1234")
    assert done.returncode == 0, done.stderr
    assert calls == ["--reuid=1000 --regid=1000 --groups=1234 the-server --flag"]
    assert "--init-groups" not in calls[0] and "--keep-groups" not in calls[0], (
        "the group the compose file gave is kept; root's own group 0 never is"
    )


@pytest.mark.parametrize("gid", ["12;touch x", "abc", "1 2", "-1", "0x10", "12\n34"])
def test_a_group_id_that_is_not_a_number_is_never_used(tmp_path: Path, gid: str) -> None:
    done, calls = run(tmp_path, "0", gid)
    assert done.returncode == 0
    assert calls == ["--reuid=1000 --regid=1000 --clear-groups the-server --flag"]
    assert "not a number" in done.stderr


def test_when_it_is_not_started_as_root_it_just_runs_the_command(tmp_path: Path) -> None:
    done, calls = run(tmp_path, "1000", "1234")
    assert calls == [], "no privilege to drop"
    assert done.returncode != 0 or "the-server" in (done.stdout + done.stderr), (
        "it tried to run the command itself (there is no such program here)"
    )


def test_the_compose_override_gives_the_container_the_group_as_a_group_and_as_a_number_for_the_entrypoint() -> None:
    script = (Path(__file__).resolve().parent.parent / "deploy" / "encore").read_text(encoding="utf-8")
    override = script[script.index('cat >"$DIR/compose.helper.yaml"') :]
    assert 'group_add:\n      - "${ENCORE_HELPER_GID}"' in override
    assert "ENCORE_HELPER_GID: ${ENCORE_HELPER_GID}" in override, "the entrypoint reads it to keep that group when it drops root"
