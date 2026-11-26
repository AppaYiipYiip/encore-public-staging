"""The keys of an install (P3-30): the music server's password key and the locked backups, as the `encore` script and the installer handle them.

The functions are taken out of the script text (between the markers) and run in bash on a made-up install folder, so what is proved is the script's own
code. What is NOT proved here and is proved by walking it: that Navidrome re-encrypts on a changed key (measured on Navidrome 0.64.2 and written in
docs/tasks P3-30) and a real restore on a clean machine (P3-07).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path

import pytest

from tests.test_deploy_scripts import BASH, DEPLOY, script_lines

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

SCRIPT = (DEPLOY / "encore").read_text(encoding="utf-8")
KEY = "k" * 48
OTHER = "o" * 48


def block() -> str:
    start = SCRIPT.index("# BEGIN the keys of this install")
    end = SCRIPT.index("# END the keys of this install")
    return SCRIPT[start:end]


def sh(tmp_path: Path, body: str, env_text: str | None = None, marker: str | None = None) -> subprocess.CompletedProcess[str]:
    """Runs [body] after the key functions on a made-up install in [tmp_path]. [marker] is the text of the fingerprint file, when there is one."""
    assert BASH is not None
    (tmp_path / "navidrome").mkdir(exist_ok=True)
    if env_text is not None:
        (tmp_path / ".env").write_text(env_text, encoding="utf-8", newline="\n")
    if marker is not None:
        (tmp_path / "navidrome" / ".encore-password-key.sha256").write_text(marker, encoding="utf-8", newline="\n")
    helpers = script_lines(
        "env_value() {", "ENV_FILE=", "set_env() {", "unset_env() {", "die() {", "backups_newest_first() {", "newest_backup() {"
    )
    program = f'DIR="{tmp_path.as_posix()}"; BACKUP_DIR="$DIR/backups"; RED=""; OFF=""; set -Eeuo pipefail\n{helpers}\n{block()}\n{body}'
    return subprocess.run([BASH, "-c", program], capture_output=True, text=True, check=False, timeout=60)


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# --- the state of the password key ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env_text", "marker", "state"),
    [
        ("A=1\n", None, "none"),
        (f"A=1\nENCORE_PASSWORD_KEY={KEY}\n", None, "unmarked"),
        (f"ENCORE_PASSWORD_KEY={KEY}\n", fingerprint(KEY) + "\n", "ok"),
        (f"ENCORE_PASSWORD_KEY={OTHER}\n", fingerprint(KEY) + "\n", "different"),
        ("A=1\n", fingerprint(KEY) + "\n", "lost"),
        ("A=1\nENCORE_PASSWORD_KEY=\n", fingerprint(KEY) + "\n", "lost"),
    ],
)
def test_the_state_of_the_password_key(tmp_path: Path, env_text: str, marker: str | None, state: str) -> None:
    result = sh(tmp_path, "password_key_state", env_text, marker)
    assert result.returncode == 0 and result.stdout == state, result.stderr


def test_a_key_is_made_once_for_an_install_that_never_had_one(tmp_path: Path) -> None:
    result = sh(tmp_path, "ensure_password_key", "A=1\nENCORE_PORT=4533\n")
    assert result.returncode == 0, result.stderr
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    keys = re.findall(r"^ENCORE_PASSWORD_KEY=([A-Za-z0-9]{48})$", text, flags=re.M)
    assert len(keys) == 1 and "A=1\n" in text and "ENCORE_PORT=4533\n" in text
    again = sh(tmp_path, "ensure_password_key")
    assert again.returncode == 0 and (tmp_path / ".env").read_text(encoding="utf-8") == text, (
        "a second run must not make another key"
    )


@pytest.mark.parametrize(
    ("env_text", "marker", "words"),
    [
        (
            "A=1\n",
            fingerprint(KEY) + "\n",
            "no longer in",
        ),  # the settings file was lost or rewritten: a new key would lock everybody out for good
        (
            f"ENCORE_PASSWORD_KEY={OTHER}\n",
            fingerprint(KEY) + "\n",
            "is not the one",
        ),  # the key was changed after the accounts were locked
    ],
)
def test_a_key_that_is_gone_or_changed_is_refused_in_words_and_never_replaced(
    tmp_path: Path, env_text: str, marker: str, words: str
) -> None:
    result = sh(tmp_path, "ensure_password_key", env_text, marker)
    assert result.returncode != 0 and words in result.stderr
    assert (tmp_path / ".env").read_text(encoding="utf-8") == env_text, "the settings file must not be touched"


def test_a_key_that_works_is_proved_once_and_the_proof_is_never_rewritten(tmp_path: Path) -> None:
    result = sh(tmp_path, "confirm_password_key", f"ENCORE_PASSWORD_KEY={KEY}\n")
    assert result.returncode == 0, result.stderr
    mark = tmp_path / "navidrome" / ".encore-password-key.sha256"
    assert mark.read_text(encoding="utf-8").strip() == fingerprint(KEY)
    mark.write_text("kept as it is\n", encoding="utf-8")
    assert sh(tmp_path, "confirm_password_key").returncode == 0
    assert mark.read_text(encoding="utf-8") == "kept as it is\n"


def test_the_secrets_it_makes_are_long_plain_letters_and_differ(tmp_path: Path) -> None:
    first = sh(tmp_path, "new_secret 48").stdout.strip()
    second = sh(tmp_path, "new_secret 48").stdout.strip()
    assert re.fullmatch(r"[A-Za-z0-9]{48}", first) and re.fullmatch(r"[A-Za-z0-9]{48}", second) and first != second


# --- what a restore carries over -------------------------------------------------------------------------------------------------------


BACKUP_ENV = f"ENCORE_PORT=1111\nENCORE_NAVIDROME_ADMIN_USER=encore-admin\nENCORE_NAVIDROME_ADMIN_PASSWORD=adminpw\nENCORE_PASSWORD_KEY={OTHER}\nENCORE_MUSIC_DIR=/old\n"
HERE_ENV = f"ENCORE_PORT=4533\nENCORE_MUSIC_DIR=/music\nENCORE_NAVIDROME_ADMIN_USER=new\nENCORE_NAVIDROME_ADMIN_PASSWORD=newpw\nENCORE_PASSWORD_KEY={KEY}\n"


def test_a_restore_carries_only_the_login_and_the_key_of_the_backup(tmp_path: Path) -> None:
    (tmp_path / "backup-env").write_text(BACKUP_ENV, encoding="utf-8", newline="\n")
    carried = sh(tmp_path, 'carried_settings "$DIR/backup-env"', HERE_ENV).stdout
    assert carried.splitlines() == [
        "ENCORE_NAVIDROME_ADMIN_USER=encore-admin",
        "ENCORE_NAVIDROME_ADMIN_PASSWORD=adminpw",
        f"ENCORE_PASSWORD_KEY={OTHER}",
    ]
    merged = sh(tmp_path, 'settings_after_restore "$(carried_settings "$DIR/backup-env")"', HERE_ENV).stdout.splitlines()
    assert merged[:2] == ["ENCORE_PORT=4533", "ENCORE_MUSIC_DIR=/music"], "this computer's own settings stay as they are"
    assert merged[2:] == carried.splitlines() and f"ENCORE_PASSWORD_KEY={KEY}" not in merged, (
        "the backup's key replaces the install's"
    )


def test_a_backup_made_before_keys_existed_leaves_the_installs_own_key_alone(tmp_path: Path) -> None:
    old_backup = "ENCORE_NAVIDROME_ADMIN_USER=encore-admin\nENCORE_NAVIDROME_ADMIN_PASSWORD=adminpw\n"
    (tmp_path / "backup-env").write_text(old_backup, encoding="utf-8", newline="\n")
    merged = sh(tmp_path, 'settings_after_restore "$(carried_settings "$DIR/backup-env")"', HERE_ENV).stdout.splitlines()
    assert f"ENCORE_PASSWORD_KEY={KEY}" in merged
    assert merged.count("ENCORE_NAVIDROME_ADMIN_PASSWORD=adminpw") == 1 and "ENCORE_NAVIDROME_ADMIN_PASSWORD=newpw" not in merged


# --- the backups' files ----------------------------------------------------------------------------------------------------------------------


def touch(path: Path, age_s: int) -> None:
    path.write_bytes(b"x")
    stamp = time.time() - age_s
    import os

    os.utime(path, (stamp, stamp))


def test_locked_and_plain_backups_are_listed_together_newest_first(tmp_path: Path) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    touch(folder / "encore-backup-20261124-033000.tar.gz", 300)
    touch(folder / "encore-backup-20261125-033000.tar.gz.age", 200)
    touch(folder / "encore-backup-20261126-033000.tar.gz.age", 100)
    touch(folder / "encore-backup-20261126-033000.tar.gz.age.part", 50)  # a cut run: never a backup
    touch(folder / "notes.txt", 10)
    listing = sh(tmp_path, 'BACKUP_DIR="$DIR/backups"; backups_newest_first', "A=1\n")
    assert listing.returncode == 0, listing.stderr
    assert [Path(line).name for line in listing.stdout.splitlines()] == [
        "encore-backup-20261126-033000.tar.gz.age",
        "encore-backup-20261125-033000.tar.gz.age",
        "encore-backup-20261124-033000.tar.gz",
    ]


@pytest.mark.parametrize(
    ("name", "words"), [("encore-backup-1.tar.gz.age", "(locked)"), ("encore-backup-1.tar.gz", "NOT locked")]
)
def test_the_last_backup_says_whether_it_is_locked(tmp_path: Path, name: str, words: str) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    touch(folder / name, 5)
    body = 'BACKUP_DIR="$DIR/backups"; last_backup_text'
    text = script_lines("backups_newest_first() {", "newest_backup() {")
    assert BASH is not None
    last = SCRIPT[SCRIPT.index("last_backup_text() {") : SCRIPT.index("\n}\n", SCRIPT.index("last_backup_text() {")) + 3]
    result = subprocess.run(
        [BASH, "-c", f'DIR="{tmp_path.as_posix()}"; set -Eeuo pipefail\n{text}\n{last}\n{body}'],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0 and words in result.stdout, result.stderr


# --- what the script and the installer say and do --------------------------------------------------------------------------------------------


def test_the_compose_file_hands_the_music_server_the_installs_own_key_and_an_empty_one_is_allowed() -> None:
    """Empty is the same as no key (measured), so an install from before keys that its OLD `encore update` brings to this file still starts; what refuses to
    start without a key the install once had is the `encore` command (the next test), not the file."""
    compose = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    assert re.search(r"^\s+ND_PASSWORDENCRYPTIONKEY: \$\{ENCORE_PASSWORD_KEY:-\}$", compose, flags=re.M)


def test_every_start_of_the_script_is_guarded_against_a_key_that_is_gone() -> None:
    """start and restart refuse (guard_password_key); update and restore have their own checks; the funnel's restart is skipped with a sentence."""
    assert "start) guard_password_key; dc up -d" in SCRIPT and "restart) guard_password_key; dc restart" in SCRIPT
    funnel = SCRIPT[SCRIPT.index("tell_server_away() {") : SCRIPT.index("cmd_funnel() {")]
    assert "lost | different)" in funnel and funnel.index("lost | different)") < funnel.index("dc up -d")


def test_the_installer_makes_the_key_before_the_first_start_and_never_lets_it_reach_the_log() -> None:
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert install.index('echo "ENCORE_PASSWORD_KEY=') < install.index('dc up -d >>"$LOG"')
    secure = [line for line in install.splitlines() if "encore secure --installer" in line]
    assert secure and all(">>" not in line and "$LOG" not in line and "tee" not in line for line in secure), secure


def test_a_folder_that_holds_accounts_locked_with_a_lost_key_is_refused_by_the_installer() -> None:
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert '[ -f "$DIR/navidrome/.encore-password-key.sha256" ]' in install and "lock everybody out for good" in install


def test_update_makes_or_refuses_the_key_before_the_new_deployment_file_replaces_the_old_one() -> None:
    update = SCRIPT[SCRIPT.index("cmd_update() {") : SCRIPT.index("# The server tells its phones where it can be reached")]
    assert update.index("ensure_password_key") < update.index('mv "$DIR/compose.yaml.new" "$DIR/compose.yaml"')
    assert update.index('mv "$DIR/compose.yaml.new" "$DIR/compose.yaml"') < update.index("confirm_password_key")


def test_a_locked_backup_is_never_left_as_a_plain_file_in_the_backups_folder() -> None:
    backup = SCRIPT[SCRIPT.index("cmd_backup() {") : SCRIPT.index("cmd_restore() {")]
    # the plain archive is made in the private staging folder when the install has a backup key, and only the locked copy is written to the backups folder
    locked_branch = backup[
        backup.index("if backup_is_locked; then") : backup.index("    else\n", backup.index("if backup_is_locked; then"))
    ]
    assert (
        '"$stage/encore-backup-$stamp.tar.gz"' in locked_branch and '"$BACKUP_DIR' not in locked_branch.split("lock_archive")[0]
    )
    assert "it was not kept" in locked_branch, "a lock that fails must stop the backup, not fall back to a plain copy"


def test_restore_reads_the_key_from_a_file_or_the_keyboard_never_from_the_command() -> None:
    restore = SCRIPT[SCRIPT.index("cmd_restore() {") : SCRIPT.index("timer_available() {")]
    assert "--key-file" in restore and "read -r -s" in restore
    assert not re.search(r"--key[ =]", restore.replace("--key-file", "")), "no option may carry the key itself"
    assert "printf '%s\\n' \"$secret\" | backup_tool" in restore, "the key reaches the tool on standard input"


def test_secure_is_in_the_help_text_and_the_dispatch(tmp_path: Path) -> None:
    assert BASH is not None
    (tmp_path / "compose.yaml").write_text("name: encore\n", encoding="utf-8")
    result = subprocess.run(
        [BASH, str(DEPLOY / "encore"), "help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={"ENCORE_DIR": tmp_path.as_posix(), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "encore secure" in result.stdout and "backup key" in result.stdout.lower()
    assert re.search(r"^\s{4}secure\) shift; cmd_secure", SCRIPT, flags=re.M)
