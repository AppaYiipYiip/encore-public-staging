"""`encore backup` and `encore restore` end to end (P3-30): the real script, the real database tool, a made-up install, and a stand-in for `docker`.

The stand-in understands only `docker run ... python -m encore_server backup ...`: it turns each `-v host:container` into a rewrite of the container's path to the
host's and runs the real tool with the same standard input, so the whole path from the script's command line to the tool's output is exercised: which folder is
mounted where, which options the tool gets, what it reads on standard input, what lands in the backups folder. Everything else the script asks of Docker
(`docker compose stop`, `up`) is accepted and does nothing; `id -u` says root; `curl` says the server answers. What is NOT proved here: a real container, and
a real Navidrome (see docs/tasks P3-30 for the measurement).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from encore_server.backup import new_key
from tests.test_deploy_scripts import BASH, DEPLOY

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

SERVER_DIR = Path(__file__).resolve().parent.parent


def msys(path: Path) -> str:
    """The path as bash on Windows wants it (`/c/Users/...`): GNU tar takes `C:/...` for a remote host. On Linux it is the path itself."""
    text = path.as_posix()
    if os.name == "nt" and len(text) > 2 and text[1] == ":":
        return "/" + text[0].lower() + text[2:]
    return text


FAKE_DOCKER = r"""#!/usr/bin/env bash
# A stand-in for `docker` (tests/test_deploy_flow.py): `docker run ... IMAGE -m encore_server backup ARGS` runs the real tool on the host.
[ "${1:-}" = run ] || exit 0
shift
mounts=()
while [ $# -gt 0 ]; do
    case "$1" in
        --rm | -i) shift ;;
        --user | --network | --entrypoint) shift 2 ;;
        -v) mounts+=("$2"); shift 2 ;;
        *) break ;;
    esac
done
shift   # the image
args=()
for a in "$@"; do
    for m in "${mounts[@]:-}"; do
        [ -n "$m" ] || continue
        if [[ "$m" =~ ^(.*):(/[^:]*)(:ro)?$ ]]; then host="${BASH_REMATCH[1]}"; box="${BASH_REMATCH[2]}"; else continue; fi
        if command -v cygpath >/dev/null 2>&1; then host="$(cygpath -m "$host")"; fi
        case "$a" in "$box") a="$host"; break ;; "$box"/*) a="$host${a#"$box"}"; break ;; esac
    done
    args+=("$a")
done
shift 0
exec "$FAKE_PYTHON" "${args[@]}"
"""


def fake_bin(tmp_path: Path) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir()
    (folder / "docker").write_text(FAKE_DOCKER, encoding="utf-8", newline="\n")
    (folder / "id").write_text(
        '#!/usr/bin/env bash\n[ "${1:-}" = -u ] && echo 0 || /usr/bin/id "$@"\n', encoding="utf-8", newline="\n"
    )
    (folder / "curl").write_text(
        '#!/usr/bin/env bash\ncase " $* " in *" -w "*) printf 200 ;; *) printf \'{"serverVersion":"9.9.9"}\' ;; esac\n',
        encoding="utf-8",
        newline="\n",
    )
    (folder / "chown").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8", newline="\n")
    for name in ("docker", "id", "curl", "chown"):
        (folder / name).chmod(0o755)
    return folder


def database(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE note (text TEXT)")
    conn.execute("INSERT INTO note VALUES (?)", (marker,))
    conn.commit()
    conn.close()


def marker_of(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return str(conn.execute("SELECT text FROM note").fetchone()[0])
    finally:
        conn.close()


class Install:
    """A made-up /opt/encore."""

    def __init__(self, tmp_path: Path, key: str, label: str) -> None:
        self.root = tmp_path / f"install-{label}"
        self.root.mkdir()
        self.bin = fake_bin(tmp_path) if not (tmp_path / "bin").exists() else tmp_path / "bin"
        (self.root / "compose.yaml").write_text(
            "services:\n  navidrome:\n    environment:\n      ND_PASSWORDENCRYPTIONKEY: x\n", encoding="utf-8"
        )
        self.set_env(
            f"ENCORE_PORT=4533\nENCORE_MUSIC_DIR=/music-{label}\nENCORE_NAVIDROME_ADMIN_USER=admin-{label}\n"
            f"ENCORE_NAVIDROME_ADMIN_PASSWORD=pw-{label}\nENCORE_PASSWORD_KEY={key}\n"
        )
        database(self.root / "data" / "encore.db", f"encore-{label}")
        database(self.root / "navidrome" / "navidrome.db", f"navidrome-{label}")

    def set_env(self, text: str) -> None:
        (self.root / ".env").write_text(text, encoding="utf-8", newline="\n")

    @property
    def env(self) -> str:
        return (self.root / ".env").read_text(encoding="utf-8")

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    def lock_with(self, public: str) -> None:
        (self.root / "backup.pub").write_text(f"# test\n{public}\n", encoding="utf-8", newline="\n")

    def encore(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        assert BASH is not None
        env = {
            "PATH": f"{msys(self.bin)}:/usr/bin:/bin",
            "ENCORE_DIR": msys(self.root),
            "FAKE_PYTHON_ARGS": "",
            "FAKE_PYTHON": "",
            "PYTHONPATH": SERVER_DIR.as_posix(),
            "PYTHONUTF8": "1",
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        }
        # The stand-in runs the tool with the interpreter of the tests: `-m encore_server backup ...` (the part after the image).
        wrapper = self.bin / "fakepython"
        wrapper.write_text(
            f'#!/usr/bin/env bash\nexec "{Path(sys.executable).as_posix()}" "$@"\n', encoding="utf-8", newline="\n"
        )
        wrapper.chmod(0o755)
        env["FAKE_PYTHON"] = msys(wrapper)
        return subprocess.run(
            [BASH, str(DEPLOY / "encore"), *args],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env=env,
            cwd=SERVER_DIR,
        )


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


KEY_A = "a" * 48
KEY_B = "b" * 48


def test_a_backup_of_an_install_with_a_backup_key_is_locked_and_nothing_plain_is_left(tmp_path: Path) -> None:
    install = Install(tmp_path, KEY_A, "one")
    public, secret = new_key()
    install.lock_with(public)
    result = install.encore("backup")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "locked" in result.stdout and secret not in result.stdout + result.stderr
    files = sorted(p.name for p in install.backups.iterdir())
    assert len(files) == 1 and files[0].startswith("encore-backup-") and files[0].endswith(".tar.gz.age"), files
    blob = (install.backups / files[0]).read_bytes()
    assert b"encore-one" not in blob and KEY_A.encode() not in blob and b"pw-one" not in blob, (
        "nothing readable in a locked backup"
    )
    assert not list(install.root.glob(".backup-*")), "the private folders are gone"


def test_without_a_backup_key_a_backup_is_plain_and_says_so(tmp_path: Path) -> None:
    install = Install(tmp_path, KEY_A, "one")
    result = install.encore("backup")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NOT locked" in result.stdout and "encore secure" in result.stdout
    assert [p.name.endswith(".tar.gz") for p in install.backups.iterdir()] == [True]


def test_restoring_a_locked_backup_with_its_key_puts_the_data_and_the_key_back(tmp_path: Path) -> None:
    source = Install(tmp_path, KEY_A, "one")
    public, secret = new_key()
    source.lock_with(public)
    assert source.encore("backup").returncode == 0
    locked = next(source.backups.iterdir())
    # another computer: its own data and its own key
    target = Install(tmp_path, KEY_B, "two")
    key_file = tmp_path / "saved-key.txt"
    key_file.write_text(secret + "\n", encoding="utf-8", newline="\n")
    (target.root / "navidrome" / ".encore-password-key.sha256").write_text(fingerprint(KEY_B) + "\n", encoding="utf-8")
    result = target.encore("restore", str(locked), "--key-file", str(key_file), "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker_of(target.root / "data" / "encore.db") == "encore-one"
    assert marker_of(target.root / "navidrome" / "navidrome.db") == "navidrome-one"
    env = target.env
    assert f"ENCORE_PASSWORD_KEY={KEY_A}" in env and KEY_B not in env, (
        "the backup's key replaces this install's: the accounts in the copy are locked with it"
    )
    assert "ENCORE_NAVIDROME_ADMIN_PASSWORD=pw-one" in env and "ENCORE_MUSIC_DIR=/music-two" in env and "ENCORE_PORT=4533" in env
    assert (target.root / "navidrome" / ".encore-password-key.sha256").read_text(encoding="utf-8").strip() == fingerprint(KEY_A)
    aside = next(target.root.glob("before-restore-*"))
    assert marker_of(aside / "data" / "encore.db") == "encore-two", "what was there is set aside, not deleted"
    assert not list(target.root.glob(".restore-*")), "the private folders are gone"
    assert secret not in result.stdout + result.stderr


def test_a_wrong_key_changes_nothing_and_says_so(tmp_path: Path) -> None:
    source = Install(tmp_path, KEY_A, "one")
    public, _ = new_key()
    _, wrong = new_key()
    source.lock_with(public)
    assert source.encore("backup").returncode == 0
    locked = next(source.backups.iterdir())
    target = Install(tmp_path, KEY_B, "two")
    before_env = target.env
    key_file = tmp_path / "wrong-key.txt"
    key_file.write_text(wrong + "\n", encoding="utf-8", newline="\n")
    result = target.encore("restore", str(locked), "--key-file", str(key_file), "--yes")
    assert result.returncode != 0 and "does not open this backup" in result.stderr
    assert wrong not in result.stdout + result.stderr
    assert target.env == before_env and marker_of(target.root / "data" / "encore.db") == "encore-two"
    assert not list(target.root.glob("before-restore-*")), "nothing was set aside: nothing was started"


def test_a_locked_backup_without_any_key_is_refused(tmp_path: Path) -> None:
    source = Install(tmp_path, KEY_A, "one")
    public, _ = new_key()
    source.lock_with(public)
    assert source.encore("backup").returncode == 0
    locked = next(source.backups.iterdir())
    target = Install(tmp_path, KEY_B, "two")
    result = target.encore("restore", str(locked), "--yes", stdin="")
    assert result.returncode != 0 and "backup key" in result.stderr
    assert marker_of(target.root / "data" / "encore.db") == "encore-two"


def test_an_old_plain_backup_still_restores_and_leaves_the_installs_own_key(tmp_path: Path) -> None:
    source = Install(tmp_path, KEY_A, "one")
    assert source.encore("backup").returncode == 0  # plain: no backup key
    plain = next(source.backups.iterdir())
    assert plain.name.endswith(".tar.gz")
    # remove the key from the backup's settings file: a backup made before keys existed
    import tarfile

    old = tmp_path / "old.tar.gz"
    with tarfile.open(plain) as source_tar, tarfile.open(old, "w:gz") as target_tar:
        for member in source_tar.getmembers():
            data = source_tar.extractfile(member)
            if member.name.endswith("env") and data is not None:
                text = "".join(
                    line for line in data.read().decode().splitlines(keepends=True) if "ENCORE_PASSWORD_KEY" not in line
                ).encode()
                member.size = len(text)
                import io

                target_tar.addfile(member, io.BytesIO(text))
            else:
                target_tar.addfile(member, data)
    target = Install(tmp_path, KEY_B, "two")
    result = target.encore("restore", msys(old), "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "not locked" in result.stdout
    assert marker_of(target.root / "navidrome" / "navidrome.db") == "navidrome-one"
    assert f"ENCORE_PASSWORD_KEY={KEY_B}" in target.env and KEY_A not in target.env
