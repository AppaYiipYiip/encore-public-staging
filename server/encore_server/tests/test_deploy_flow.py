"""`encore backup`, `restore`, `secure` and `update` end to end (P3-30): the real script, the real database tool, a made-up install, and a stand-in for `docker`.

The stand-in understands `docker run ... python -m encore_server backup ...` (it turns each `-v host:container` into a rewrite of the container's path to the host's and
runs the real tool with the same standard input), `docker run --entrypoint cat IMAGE /app/deploy/FILE` (it prints FILE from a made-up image folder) and accepts
everything else (`docker compose stop`, `up`, `pull`) doing nothing, writing each call it understood to a log so a test can say what happened first. `id -u` says
root, `curl` says the server answers and, when asked to sign the administrator in, says what the test chose. What is NOT proved here: a real container, and a real
Navidrome (see docs/tasks P3-30 and docs/evidence e08 for the measurement).
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from encore_server.backup import decrypt_file, new_key, parse_secret_key
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
# A stand-in for `docker` (tests/test_deploy_flow.py).
if [[ " $* " == *" --entrypoint cat "* ]]; then
    last="${@: -1}"
    echo "fetch:$(basename "$last")" >>"$FAKE_LOG"
    cat "$FAKE_IMAGE_DIR/$(basename "$last")"
    exit $?
fi
if [ "${1:-}" != run ]; then
    echo "docker:${*:1:4}" >>"$FAKE_LOG"
    if [ "${FAKE_FAIL:-}" = up ] && [[ " $* " == *" up "* ]]; then exit 1; fi
    exit 0
fi
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
echo "tool:${args[3]:-}" >>"$FAKE_LOG"
exec "$FAKE_PYTHON" "${args[@]}"
"""

FAKE_CURL = r"""#!/usr/bin/env bash
case " $* " in
    *"/rest/ping"*) if [ "${FAKE_PING:-ok}" = ok ]; then printf '{"subsonic-response":{"status":"ok","version":"1.16.1"}}'; else printf '{"subsonic-response":{"status":"failed","error":{"code":40}}}'; fi ;;
    *" -w "*) printf 200 ;;
    *) printf '{"serverVersion":"9.9.9"}' ;;
esac
"""


def fake_bin(tmp_path: Path) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    (folder / "docker").write_text(FAKE_DOCKER, encoding="utf-8", newline="\n")
    (folder / "id").write_text(
        '#!/usr/bin/env bash\n[ "${1:-}" = -u ] && echo 0 || /usr/bin/id "$@"\n', encoding="utf-8", newline="\n"
    )
    (folder / "curl").write_text(FAKE_CURL, encoding="utf-8", newline="\n")
    (folder / "chown").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8", newline="\n")
    (folder / "ip").write_text(
        '#!/usr/bin/env bash\necho "1.1.1.1 via 10.0.0.1 dev eth0 src 10.0.0.23 uid 0"\n', encoding="utf-8", newline="\n"
    )
    (folder / "fakepython").write_text(
        f'#!/usr/bin/env bash\nexec "{Path(sys.executable).as_posix()}" "$@"\n', encoding="utf-8", newline="\n"
    )
    for name in ("docker", "id", "curl", "chown", "ip", "fakepython"):
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


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


KEY_A = "a" * 48
KEY_B = "b" * 48
NEW_COMPOSE = "services:\n  navidrome:\n    environment:\n      ND_PASSWORDENCRYPTIONKEY: ${ENCORE_PASSWORD_KEY:-}\n"
OLD_COMPOSE = "services:\n  navidrome:\n    environment:\n      ND_LOGLEVEL: info\n"


class Install:
    """A made-up /opt/encore, and the image the script would pull."""

    def __init__(self, tmp_path: Path, key: str | None, label: str, compose: str = NEW_COMPOSE) -> None:
        self.root = tmp_path / f"install-{label}"
        self.root.mkdir()
        self.tmp = tmp_path
        self.bin = fake_bin(tmp_path)
        self.image = tmp_path / f"image-{label}"
        self.image.mkdir()
        (self.image / "compose.yaml").write_text(NEW_COMPOSE, encoding="utf-8", newline="\n")
        (self.image / "encore").write_text("#!/bin/sh\necho the new encore command\n", encoding="utf-8", newline="\n")
        self.log = tmp_path / f"calls-{label}.log"
        self.log.write_text("", encoding="utf-8")
        (self.root / "compose.yaml").write_text(compose, encoding="utf-8", newline="\n")
        env = f"ENCORE_PORT=4533\nENCORE_MUSIC_DIR=/music-{label}\nENCORE_NAVIDROME_ADMIN_USER=admin-{label}\nENCORE_NAVIDROME_ADMIN_PASSWORD=pw-{label}\n"
        if key is not None:
            env += f"ENCORE_PASSWORD_KEY={key}\n"
        self.set_env(env)
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

    @property
    def mark(self) -> Path:
        return self.root / "navidrome" / ".encore-password-key.sha256"

    def lock_with(self, public: str) -> None:
        (self.root / "backup.pub").write_text(f"# test\n{public}\n", encoding="utf-8", newline="\n")

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()

    def encore(self, *args: str, stdin: str = "", ping: str = "ok", fail: str = "") -> subprocess.CompletedProcess[str]:
        assert BASH is not None
        env = {
            "PATH": f"{msys(self.bin)}:/usr/bin:/bin",
            "ENCORE_DIR": msys(self.root),
            "ENCORE_BIN": msys(self.root / "encore-command"),
            "FAKE_PYTHON": msys(self.bin / "fakepython"),
            "FAKE_IMAGE_DIR": msys(self.image),
            "FAKE_LOG": msys(self.log),
            "FAKE_PING": ping,
            "FAKE_FAIL": fail,
            "PYTHONPATH": SERVER_DIR.as_posix(),
            "PYTHONUTF8": "1",
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        }
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


def secret_in(text: str) -> str:
    found = re.findall(r"AGE-SECRET-KEY-1[A-Z0-9]+", text)
    assert len(found) == 1, f"the secret must be shown exactly once, found {len(found)}"
    return found[0]


# ---------------------------------------------------------------------------------------------------------------------- backup and restore


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


def test_a_cut_run_leaves_nothing_that_the_next_backup_trips_over(tmp_path: Path) -> None:
    install = Install(tmp_path, KEY_A, "one")
    install.backups.mkdir()
    (install.backups / "encore-backup-20261101-030000.tar.gz.age.part").write_bytes(b"half")
    assert install.encore("backup", "--quiet").returncode == 0
    assert not list(install.backups.glob("*.part"))


def test_restoring_a_locked_backup_with_its_key_puts_the_data_and_the_key_back_and_keeps_that_key_for_the_next_backups(
    tmp_path: Path,
) -> None:
    source = Install(tmp_path, KEY_A, "one")
    public, secret = new_key()
    source.lock_with(public)
    assert source.encore("backup").returncode == 0
    locked = next(source.backups.iterdir())
    # another computer: its own data, its own password key and ITS OWN backup key (a different one, which nobody saved)
    target = Install(tmp_path, KEY_B, "two")
    other_public, _ = new_key()
    target.lock_with(other_public)
    key_file = tmp_path / "saved-key.txt"
    key_file.write_text(secret + "\n", encoding="utf-8", newline="\n")
    target.mark.write_text(fingerprint(KEY_B) + "\n", encoding="utf-8")
    result = target.encore("restore", str(locked), "--key-file", str(key_file), "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker_of(target.root / "data" / "encore.db") == "encore-one"
    assert marker_of(target.root / "navidrome" / "navidrome.db") == "navidrome-one"
    env = target.env
    assert f"ENCORE_PASSWORD_KEY={KEY_A}" in env and KEY_B not in env, (
        "the backup's key replaces this install's: the accounts in the copy are locked with it"
    )
    assert "ENCORE_NAVIDROME_ADMIN_PASSWORD=pw-one" in env and "ENCORE_MUSIC_DIR=/music-two" in env and "ENCORE_PORT=4533" in env
    assert target.mark.read_text(encoding="utf-8").strip() == fingerprint(KEY_A)
    aside = next(target.root.glob("before-restore-*"))
    assert marker_of(aside / "data" / "encore.db") == "encore-two", "what was there is set aside, not deleted"
    assert not list(target.root.glob(".restore-*")), "the private folders are gone"
    assert secret not in result.stdout + result.stderr
    # the install's backups are now locked with the key the Host just used, so the one key they saved opens everything from now on
    pub_lines = [
        line
        for line in (target.root / "backup.pub").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert pub_lines == [str(parse_secret_key(secret).to_public())] and other_public not in pub_lines
    assert "locked with the key you just used" in result.stdout
    assert target.encore("backup", "--quiet").returncode == 0
    newest = max(target.backups.iterdir(), key=lambda p: p.stat().st_mtime)
    opened = tmp_path / "opened-after-restore.tar.gz"
    decrypt_file(newest, opened, parse_secret_key(secret))
    assert opened.stat().st_size > 0


def test_a_wrong_key_changes_nothing_and_says_so(tmp_path: Path) -> None:
    source = Install(tmp_path, KEY_A, "one")
    public, _ = new_key()
    _, wrong = new_key()
    source.lock_with(public)
    assert source.encore("backup").returncode == 0
    locked = next(source.backups.iterdir())
    target = Install(tmp_path, KEY_B, "two")
    target.lock_with(new_key()[0])
    before_env, before_pub = target.env, (target.root / "backup.pub").read_text(encoding="utf-8")
    key_file = tmp_path / "wrong-key.txt"
    key_file.write_text(wrong + "\n", encoding="utf-8", newline="\n")
    result = target.encore("restore", str(locked), "--key-file", str(key_file), "--yes")
    assert result.returncode != 0 and "does not open this backup" in result.stderr
    assert wrong not in result.stdout + result.stderr
    assert target.env == before_env and marker_of(target.root / "data" / "encore.db") == "encore-two"
    assert (target.root / "backup.pub").read_text(encoding="utf-8") == before_pub, (
        "a failed restore must not change the key the backups are locked with"
    )
    assert not list(target.root.glob("before-restore-*")), "nothing was set aside: nothing was started"


def test_a_locked_backup_without_any_key_is_refused_and_so_is_a_key_file_option_without_a_file(tmp_path: Path) -> None:
    source = Install(tmp_path, KEY_A, "one")
    public, _ = new_key()
    source.lock_with(public)
    assert source.encore("backup").returncode == 0
    locked = next(source.backups.iterdir())
    target = Install(tmp_path, KEY_B, "two")
    result = target.encore("restore", str(locked), "--yes", stdin="")
    assert result.returncode != 0 and "backup key" in result.stderr
    assert marker_of(target.root / "data" / "encore.db") == "encore-two"
    dangling = target.encore("restore", str(locked), "--yes", "--key-file")
    assert dangling.returncode != 0 and "--key-file needs" in dangling.stderr


def test_an_old_plain_backup_still_restores_and_leaves_the_installs_own_key(tmp_path: Path) -> None:
    source = Install(tmp_path, KEY_A, "one")
    assert source.encore("backup").returncode == 0  # plain: no backup key
    plain = next(source.backups.iterdir())
    assert plain.name.endswith(".tar.gz")
    # remove the key from the backup's settings file: a backup made before keys existed
    old = tmp_path / "old.tar.gz"
    with tarfile.open(plain) as source_tar, tarfile.open(old, "w:gz") as target_tar:
        for member in source_tar.getmembers():
            data = source_tar.extractfile(member)
            if member.name.endswith("env") and data is not None:
                text = "".join(
                    line for line in data.read().decode().splitlines(keepends=True) if "ENCORE_PASSWORD_KEY" not in line
                ).encode()
                member.size = len(text)
                target_tar.addfile(member, io.BytesIO(text))
            else:
                target_tar.addfile(member, data)
    target = Install(tmp_path, KEY_B, "two")
    result = target.encore("restore", msys(old), "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "not locked" in result.stdout
    assert marker_of(target.root / "navidrome" / "navidrome.db") == "navidrome-one"
    assert f"ENCORE_PASSWORD_KEY={KEY_B}" in target.env and KEY_A not in target.env


# ---------------------------------------------------------------------------------------------------------------------- encore secure


def test_secure_on_a_fresh_install_proves_the_key_makes_the_backup_key_and_shows_the_secret_once(tmp_path: Path) -> None:
    """What the installer does at its end (`encore secure --installer`) on the install it has just started."""
    install = Install(tmp_path, KEY_A, "fresh")
    result = install.encore("secure", "--installer")
    assert result.returncode == 0, result.stdout + result.stderr
    secret = secret_in(result.stdout)
    assert "AGE-SECRET-KEY" not in result.stderr
    assert install.mark.read_text(encoding="utf-8").strip() == fingerprint(KEY_A), (
        "the key is marked once the music server accepted it"
    )
    keys = [
        line
        for line in (install.root / "backup.pub").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert len(keys) == 1 and keys[0].startswith("age1") and keys[0] == str(parse_secret_key(secret).to_public())
    for file in install.root.rglob("*"):
        if file.is_file() and file.suffix != ".db":
            assert b"AGE-SECRET-KEY" not in file.read_bytes(), f"the secret half reached {file}"
    before = {p: p.read_bytes() for p in (install.root / ".env", install.root / "backup.pub", install.mark)}
    again = install.encore("secure", "--installer")
    assert again.returncode == 0 and "Backups are locked" in again.stdout and "AGE-SECRET-KEY" not in again.stdout
    assert {p: p.read_bytes() for p in before} == before, "a second run changes nothing"
    assert not install.backups.exists() or not list(install.backups.iterdir()), "nothing is backed up when nothing is changed"


def test_a_key_the_music_server_does_not_accept_is_not_marked_as_the_right_one(tmp_path: Path) -> None:
    install = Install(tmp_path, KEY_A, "fresh")
    result = install.encore("secure", "--installer", ping="fail")
    assert result.returncode != 0 and "NOT marked" in result.stderr
    assert not install.mark.exists(), "a wrong fingerprint would lock the right key out"


def test_secure_locks_the_plain_backups_of_before_and_keeps_their_order(tmp_path: Path) -> None:
    install = Install(tmp_path, KEY_A, "old")
    assert install.encore("backup", "--quiet").returncode == 0
    first = next(install.backups.iterdir())
    os.utime(first, (1_700_000_000, 1_700_000_000))
    second = first.with_name("encore-backup-20261101-030000.tar.gz")
    second.write_bytes(first.read_bytes())
    os.utime(second, (1_700_100_000, 1_700_100_000))
    result = install.encore("secure", "--installer")
    assert result.returncode == 0, result.stdout + result.stderr
    secret = secret_in(result.stdout)
    assert "older backup(s) were locked" in result.stdout
    names = sorted(p.name for p in install.backups.iterdir())
    assert all(name.endswith(".tar.gz.age") for name in names) and len(names) == 2, f"no plain archive may remain: {names}"
    locked = install.backups / "encore-backup-20261101-030000.tar.gz.age"
    assert locked.stat().st_mtime == pytest.approx(1_700_100_000, abs=2), (
        "the age of a backup is kept: the keep-seven rule goes by it"
    )
    opened = tmp_path / "opened.tar.gz"
    decrypt_file(locked, opened, parse_secret_key(secret))
    with tarfile.open(opened) as archive:
        assert {"encore.db", "navidrome.db", "env"} <= {m.name.removeprefix("./") for m in archive.getmembers()}


# ---------------------------------------------------------------------------------------------------------------------- encore update


def test_update_of_an_install_from_before_keys_backs_up_first_then_makes_the_key_and_proves_it(tmp_path: Path) -> None:
    install = Install(tmp_path, None, "before", compose=OLD_COMPOSE)
    result = install.encore("update")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = install.calls()
    first_backup = next(i for i, call in enumerate(calls) if call == "tool:--encore-db")
    first_fetch = next(i for i, call in enumerate(calls) if call.startswith("fetch:"))
    assert first_backup < first_fetch, f"the backup must come before anything is fetched or replaced: {calls}"
    kept = next(i for i, call in enumerate(calls) if call.startswith("docker:tag ") and call.endswith(":before-update"))
    pulled = next(i for i, call in enumerate(calls) if " pull" in call and call.startswith("docker:compose"))
    assert first_backup < kept < pulled, f"the running program is kept under its own name before the pull moves the tag: {calls}"
    record = (install.root / "update-record.txt").read_text(encoding="utf-8")
    assert "image=ghcr.io/appayiipyiip/encore-server:before-update" in record
    assert f"backup={install.backups}" in record.replace("\\", "/") or "backup=" in record and ".tar.gz" in record
    assert "A backup was made first" in result.stdout
    assert list(install.backups.iterdir()), "the backup exists"
    assert (install.root / "compose.yaml").read_text(encoding="utf-8") == NEW_COMPOSE
    assert (install.root / "compose.yaml.before-update").read_text(encoding="utf-8") == OLD_COMPOSE
    key = re.search(r"^ENCORE_PASSWORD_KEY=([A-Za-z0-9]{48})$", install.env, flags=re.M)
    assert key is not None, install.env
    assert install.mark.read_text(encoding="utf-8").strip() == fingerprint(key.group(1)), (
        "the key is marked after the start that proved it"
    )
    assert "Your backups are not locked yet" in result.stdout
    assert (install.root / "encore-command").read_text(encoding="utf-8").startswith("#!/bin/sh"), (
        "the new command replaced the old one last"
    )


def test_update_of_an_install_whose_key_was_lost_is_refused_and_changes_nothing(tmp_path: Path) -> None:
    install = Install(tmp_path, None, "lost", compose=OLD_COMPOSE)
    install.mark.write_text(fingerprint(KEY_A) + "\n", encoding="utf-8")
    compose_before = (install.root / "compose.yaml").read_bytes()
    env_before = install.env
    result = install.encore("update")
    assert result.returncode != 0 and "no longer in" in result.stderr
    assert (install.root / "compose.yaml").read_bytes() == compose_before, "the deployment file must not be replaced"
    assert install.env == env_before and not (install.root / "compose.yaml.before-update").exists()
    assert not (install.root / "encore-command").exists()


def test_update_of_an_install_whose_key_was_changed_is_refused_too(tmp_path: Path) -> None:
    install = Install(tmp_path, KEY_B, "changed", compose=NEW_COMPOSE)
    install.mark.write_text(fingerprint(KEY_A) + "\n", encoding="utf-8")
    result = install.encore("update")
    assert result.returncode != 0 and "is not the one" in result.stderr
    assert f"ENCORE_PASSWORD_KEY={KEY_B}" in install.env


def test_when_the_new_version_does_not_start_the_way_back_names_the_old_program_the_old_file_and_the_backup(
    tmp_path: Path,
) -> None:
    """The old deployment file alone starts the NEW program again (the tag moves), so the sentence needs the kept image, the file and the backup made first."""
    install = Install(tmp_path, None, "stuck", compose=OLD_COMPOSE)
    result = install.encore("update", fail="up")
    assert result.returncode != 0
    text = result.stderr
    assert (
        "ENCORE_TAG=before-update" in text
        and "compose.yaml.before-update" in text
        and "sudo encore restore" in text
        and ".tar.gz" in text
    ), text
    record = (install.root / "update-record.txt").read_text(encoding="utf-8")
    assert "backup=" in record and ".tar.gz" in record and "image=" in record
    assert (install.root / "compose.yaml.before-update").read_text(encoding="utf-8") == OLD_COMPOSE


def test_the_installer_tells_the_host_where_the_admin_pages_are() -> None:
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "There is no Encore admin page" not in install
    assert "http://${HOST_IP}:${PORT}/admin" in install
