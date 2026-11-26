"""A backup is secret material (P3-30): it is locked to a public key kept on the computer and opened only with the secret key the Host saved.

What is proven here: the round trip on a file bigger than memory-friendly chunks, that nothing readable is left in the locked file, that a wrong key and a
damaged file are two different sentences, that no message ever carries a key, that a cut run leaves nothing that looks whole, and the command line the
`encore` script uses (the secret on standard input, never in an argument).
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from pyrage import x25519

from encore_server.backup import (
    BackupError,
    command,
    decrypt_file,
    encrypt_file,
    new_key,
    parse_secret_key,
    read_public_key,
)

MARKER = b"identity-private-key-and-the-song-signing-secret"


def archive(tmp_path: Path, size: int = 3 * 1024 * 1024) -> Path:
    """A stand-in for the packed backup: random bytes with a marker a thief would be looking for inside."""
    path = tmp_path / "encore-backup-20261126-030000.tar.gz"
    path.write_bytes(MARKER + os.urandom(size))
    return path


def key_file(tmp_path: Path, public: str) -> Path:
    path = tmp_path / "backup.pub"
    path.write_text(f"# the key that locks the backups\n{public}\n", encoding="utf-8")
    return path


def test_a_new_pair_has_a_public_half_that_locks_and_a_secret_half_that_opens(tmp_path: Path) -> None:
    public, secret = new_key()
    assert public.startswith("age1")
    assert secret.startswith("AGE-SECRET-KEY-1")
    assert new_key() != (public, secret)
    plain = archive(tmp_path)
    locked = tmp_path / (plain.name + ".age")
    assert encrypt_file(plain, locked, read_public_key(key_file(tmp_path, public))) > plain.stat().st_size
    opened = tmp_path / "opened.tar.gz"
    assert decrypt_file(locked, opened, parse_secret_key(secret)) == plain.stat().st_size
    assert opened.read_bytes() == plain.read_bytes()


def test_nothing_readable_is_left_in_the_locked_file(tmp_path: Path) -> None:
    public, _ = new_key()
    plain = archive(tmp_path)
    locked = tmp_path / "locked.age"
    encrypt_file(plain, locked, read_public_key(key_file(tmp_path, public)))
    assert MARKER not in locked.read_bytes()
    assert plain.read_bytes()[: len(MARKER)] == MARKER  # and the source was not touched


def test_a_key_that_is_not_the_one_is_told_apart_from_a_damaged_file(tmp_path: Path) -> None:
    public, secret = new_key()
    _, other_secret = new_key()
    plain = archive(tmp_path, size=4096)
    locked = tmp_path / "locked.age"
    encrypt_file(plain, locked, read_public_key(key_file(tmp_path, public)))
    with pytest.raises(BackupError, match="does not open this backup"):
        decrypt_file(locked, tmp_path / "a", parse_secret_key(other_secret))
    blob = bytearray(locked.read_bytes())
    blob[len(blob) // 2] ^= 0xFF  # one changed byte in the middle
    locked.write_bytes(bytes(blob))
    with pytest.raises(BackupError, match="damaged or was changed"):
        decrypt_file(locked, tmp_path / "b", parse_secret_key(secret))
    locked.write_bytes(bytes(blob)[: len(blob) // 2])  # a copy that was cut short
    with pytest.raises(BackupError, match="damaged or was changed"):
        decrypt_file(locked, tmp_path / "c", parse_secret_key(secret))
    assert not list(tmp_path.glob("*.part")), "a failed opening must leave no half file"
    assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists() and not (tmp_path / "c").exists()


def test_no_message_ever_carries_a_key(tmp_path: Path) -> None:
    public, secret = new_key()
    _, other_secret = new_key()
    plain = archive(tmp_path, size=2048)
    locked = tmp_path / "locked.age"
    encrypt_file(plain, locked, read_public_key(key_file(tmp_path, public)))
    messages = []
    for call in (
        lambda: decrypt_file(locked, tmp_path / "x", parse_secret_key(other_secret)),
        lambda: parse_secret_key("AGE-SECRET-KEY-1" + "Q" * 50),
        lambda: parse_secret_key(secret[:-3]),
        lambda: read_public_key(key_file(tmp_path, public[:-2])),
    ):
        with pytest.raises(BackupError) as caught:
            call()
        messages.append(str(caught.value))
    assert messages and all(secret not in m and other_secret not in m and public not in m for m in messages)
    assert all(not m.startswith(("AGE-", "age1")) and "Traceback" not in m for m in messages)


def test_a_public_key_file_must_hold_exactly_one_key(tmp_path: Path) -> None:
    public, _ = new_key()
    other, _ = new_key()
    two = tmp_path / "two.pub"
    two.write_text(f"{public}\n{other}\n", encoding="utf-8")
    with pytest.raises(BackupError, match="should hold one backup key"):
        read_public_key(two)
    empty = tmp_path / "empty.pub"
    empty.write_text("# nothing here\n\n", encoding="utf-8")
    with pytest.raises(BackupError, match="holds 0"):
        read_public_key(empty)
    assert isinstance(read_public_key(key_file(tmp_path, public)), x25519.Recipient)


def test_a_result_that_exists_is_never_overwritten_and_a_missing_source_is_a_sentence(tmp_path: Path) -> None:
    public, secret = new_key()
    recipient = read_public_key(key_file(tmp_path, public))
    plain = archive(tmp_path, size=1024)
    target = tmp_path / "locked.age"
    target.write_bytes(b"an older backup")
    with pytest.raises(BackupError, match="already exists"):
        encrypt_file(plain, target, recipient)
    assert target.read_bytes() == b"an older backup"
    with pytest.raises(BackupError, match="was not found"):
        encrypt_file(tmp_path / "nothing", tmp_path / "t.age", recipient)
    with pytest.raises(BackupError, match="was not found"):
        decrypt_file(tmp_path / "nothing.age", tmp_path / "t", parse_secret_key(secret))


# --- the command line the `encore` script uses -------------------------------------------------------------------------------------------


def run(argv: list[str], stdin: str | None = None, monkeypatch: pytest.MonkeyPatch | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    if stdin is not None and monkeypatch is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return command(argv, out=out, err=err), out.getvalue(), err.getvalue()


def test_the_command_line_makes_a_key_locks_and_opens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    status, out, _ = run(["--new-key"])
    lines = dict(line.split("=", 1) for line in out.strip().splitlines())
    assert status == 0 and set(lines) == {"public", "secret"}
    plain = archive(tmp_path, size=5000)
    locked = tmp_path / "locked.age"
    status, out, err = run(["--encrypt", str(plain), "--to", str(key_file(tmp_path, lines["public"])), "--out", str(locked)])
    assert status == 0 and "locked" in out and err == ""
    assert lines["secret"] not in out
    opened = tmp_path / "opened"
    status, out, err = run(
        ["--decrypt", str(locked), "--out", str(opened)], stdin=lines["secret"] + "\n", monkeypatch=monkeypatch
    )
    assert status == 0 and "opened" in out and err == ""
    assert opened.read_bytes() == plain.read_bytes()
    assert lines["secret"] not in out


def test_the_command_line_refuses_a_wrong_key_with_a_sentence_and_no_key_in_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public, _ = new_key()
    _, wrong = new_key()
    plain = archive(tmp_path, size=1000)
    locked = tmp_path / "locked.age"
    run(["--encrypt", str(plain), "--to", str(key_file(tmp_path, public)), "--out", str(locked)])
    status, out, err = run(["--decrypt", str(locked), "--out", str(tmp_path / "o")], stdin=wrong + "\n", monkeypatch=monkeypatch)
    assert status == 1 and out == ""
    assert err.startswith("backup: That key does not open this backup.") and wrong not in err


def test_the_command_line_refuses_an_empty_standard_input_and_a_missing_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public, _ = new_key()
    plain = archive(tmp_path, size=100)
    locked = tmp_path / "locked.age"
    run(["--encrypt", str(plain), "--to", str(key_file(tmp_path, public)), "--out", str(locked)])
    status, _, err = run(["--decrypt", str(locked), "--out", str(tmp_path / "o")], stdin="", monkeypatch=monkeypatch)
    assert status == 1 and "not a backup key" in err
    status, _, err = run(["--encrypt", str(plain)])
    assert status == 1 and "--to KEYFILE" in err
    status, _, err = run(["--decrypt", str(locked)])
    assert status == 1 and "--out FILE" in err


def test_the_usage_line_names_the_new_options() -> None:
    status, _, err = run(["--nonsense"])
    assert status == 2
    assert "--new-key" in err and "--encrypt" in err and "--decrypt" in err


def test_the_key_a_host_saved_can_be_checked_against_the_public_key_of_the_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public, secret = new_key()
    _, other = new_key()
    keyfile = key_file(tmp_path, public)
    status, out, err = run(["--matches", str(keyfile)], stdin=secret + "\n", monkeypatch=monkeypatch)
    assert status == 0 and "that is the key" in out and err == ""
    status, out, err = run(["--matches", str(keyfile)], stdin=other + "\n", monkeypatch=monkeypatch)
    assert status == 1 and out == "" and "not the key of this install" in err and other not in err
    status, _, err = run(["--matches", str(keyfile)], stdin="a note, not a key\n", monkeypatch=monkeypatch)
    assert status == 1 and "not a backup key" in err
