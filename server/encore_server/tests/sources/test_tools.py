"""The yt-dlp the server runs (docs/11 ADR-R39): which release is eligible, how a stored copy is kept, and how a start finds it (or does not)."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from encore_server.sources.youtube import tools
from encore_server.sources.youtube.tools import Pointer, Release, ToolStore, activate, newest_eligible, version_key

NOW = 1_800_000_000.0  # 2027-01-15, any fixed moment
DAY = 86400.0


def iso(epoch: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


def pypi(releases: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {"info": {"name": "yt-dlp"}, "releases": releases}


def wheel_file(version: str, age_s: float, *, yanked: bool = False, name: str | None = None) -> dict[str, Any]:
    filename = name or f"yt_dlp-{version}-py3-none-any.whl"
    return {
        "filename": filename,
        "url": f"https://files.example.test/{filename}",
        "upload_time_iso_8601": iso(NOW - age_s),
        "yanked": yanked,
        "digests": {"sha256": hashlib.sha256(version.encode()).hexdigest()},
    }


def make_wheel(path: Path, version: str, body: str = "MARK = 1\n") -> bytes:
    """A real zip that Python can import: `yt_dlp/__init__.py` (and `version.py`, as the canary reads it)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("yt_dlp/__init__.py", body)
        archive.writestr("yt_dlp/version.py", f"__version__ = {version!r}\n")
    return path.read_bytes()


# ------------------------------------------------------------------------------------------------ which release


def test_versions_compare_as_numbers_and_anything_else_is_not_a_release() -> None:
    assert version_key("2026.10.21") == (2026, 10, 21)
    assert version_key("2026.9.3") < version_key("2026.10.2")  # type: ignore[operator]
    assert version_key("2026.10.21.232818") > version_key("2026.10.21")  # type: ignore[operator]
    for text in ("", "2026.10.21.dev0", "2026.10.21rc1", "latest", "2026..1"):
        assert version_key(text) is None, text


def test_the_newest_release_older_than_a_day_is_chosen_and_a_younger_one_waits() -> None:
    meta = pypi(
        {
            "2026.10.01": [wheel_file("2026.10.01", 30 * DAY)],
            "2026.10.20": [wheel_file("2026.10.20", 3 * DAY)],
            "2026.10.22": [wheel_file("2026.10.22", 2 * 3600)],  # two hours old: not yet
        }
    )

    chosen = newest_eligible(meta, now=NOW, above=(2026, 10, 1))

    assert chosen is not None and chosen.version == "2026.10.20"
    assert chosen.filename == "yt_dlp-2026.10.20-py3-none-any.whl" and chosen.uploaded_at == NOW - 3 * DAY


def test_once_a_day_has_passed_the_young_release_is_chosen() -> None:
    meta = pypi({"2026.10.22": [wheel_file("2026.10.22", DAY + 1)]})

    chosen = newest_eligible(meta, now=NOW, above=())

    assert chosen is not None and chosen.version == "2026.10.22"


def test_nothing_is_chosen_that_is_not_newer_than_what_runs() -> None:
    meta = pypi({"2026.10.20": [wheel_file("2026.10.20", 3 * DAY)], "2026.10.21": [wheel_file("2026.10.21", 2 * DAY)]})

    assert newest_eligible(meta, now=NOW, above=(2026, 10, 21)) is None
    assert newest_eligible(meta, now=NOW, above=(2026, 10, 20)).version == "2026.10.21"  # type: ignore[union-attr]


def test_a_yanked_release_a_pre_release_a_bad_release_and_a_release_without_a_plain_wheel_are_never_chosen() -> None:
    meta = pypi(
        {
            "2026.10.25": [wheel_file("2026.10.25", 3 * DAY, yanked=True)],
            "2026.10.24.dev0": [wheel_file("2026.10.24.dev0", 3 * DAY)],
            "2026.10.23": [
                {
                    "filename": "yt_dlp-2026.10.23.tar.gz",
                    "url": "x",
                    "upload_time_iso_8601": iso(NOW - 3 * DAY),
                    "digests": {"sha256": "x"},
                }
            ],
            "2026.10.22": [wheel_file("2026.10.22", 3 * DAY)],
            "2026.10.21": [wheel_file("2026.10.21", 3 * DAY)],
        }
    )

    chosen = newest_eligible(meta, now=NOW, above=(), skip=["2026.10.22"])

    assert chosen is not None and chosen.version == "2026.10.21"


def test_an_answer_that_is_not_what_pypi_sends_chooses_nothing() -> None:
    for meta in (
        {},
        {"releases": []},
        {"releases": {"2026.1.1": "no"}},
        {"releases": {"2026.1.1": [{"filename": "x-py3-none-any.whl"}]}},
    ):
        assert newest_eligible(meta, now=NOW, above=()) is None


# ------------------------------------------------------------------------------------------------ the store


def release_for(version: str, data: bytes) -> Release:
    return Release(
        version,
        f"yt_dlp-{version}-py3-none-any.whl",
        "https://files.example.test/x",
        hashlib.sha256(data).hexdigest(),
        NOW - 2 * DAY,
    )


def test_a_download_is_stored_only_when_it_is_what_pypi_described(tmp_path: Path) -> None:
    store = ToolStore(tmp_path / "tools")
    data = b"wheel bytes"

    stored = store.save_wheel(release_for("2026.11.01", data), data)

    assert stored.read_bytes() == data
    with pytest.raises(ValueError, match="checksum"):
        store.save_wheel(release_for("2026.11.02", data), b"something else")
    assert [p.name for p in store.wheels.iterdir()] == ["yt_dlp-2026.11.01-py3-none-any.whl"], (
        "a refused download leaves nothing behind"
    )


def test_the_pointer_is_written_whole_and_read_back(tmp_path: Path) -> None:
    store = ToolStore(tmp_path)
    assert store.read_pointer() is None

    store.write_pointer(Pointer("2026.11.01", "yt_dlp-2026.11.01-py3-none-any.whl", "ab" * 32))

    assert store.read_pointer() == Pointer("2026.11.01", "yt_dlp-2026.11.01-py3-none-any.whl", "ab" * 32)
    assert [p.name for p in tmp_path.iterdir()] == ["current.json"], "no temporary file is left"


def test_pruning_keeps_what_is_named_and_removes_the_rest_including_a_half_download(tmp_path: Path) -> None:
    store = ToolStore(tmp_path)
    store.wheels.mkdir(parents=True)
    for name in ("a-py3-none-any.whl", "b-py3-none-any.whl", ".part-xyz.whl"):
        (store.wheels / name).write_bytes(b"x")

    store.prune({"b-py3-none-any.whl"})

    assert [p.name for p in store.wheels.iterdir()] == ["b-py3-none-any.whl"]


# ------------------------------------------------------------------------------------------------ the start


@pytest.fixture()
def clean_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """A start sees neither a yt_dlp already imported nor a path another test changed; the test's changes are undone afterwards."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "yt_dlp", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setenv("PYTHONPATH", "/already/there")


def staged(tmp_path: Path, version: str = "2099.1.1") -> tuple[ToolStore, Path]:
    store = ToolStore(tmp_path / "tools")
    release = release_for(version, b"")
    wheel = store.wheels / release.filename
    data = make_wheel(wheel, version)
    store.write_pointer(Pointer(version, release.filename, hashlib.sha256(data).hexdigest()))
    return store, wheel


def test_a_stored_newer_copy_is_put_first_on_the_import_path_and_in_the_environment(tmp_path: Path, clean_path: None) -> None:
    import os

    store, wheel = staged(tmp_path)

    active = activate(store, image="2026.10.21")

    assert active is not None and active.version == "2099.1.1" and active.wheel == wheel
    assert sys.path[0] == str(wheel)
    assert os.environ["PYTHONPATH"] == f"{wheel}{os.pathsep}/already/there", (
        "a child process and the playlist reader see the same copy"
    )


def test_the_stored_copy_really_wins_over_the_installed_one_in_a_fresh_interpreter(tmp_path: Path) -> None:
    store, wheel = staged(tmp_path)
    code = (
        "import sys; from pathlib import Path; from encore_server.sources.youtube.tools import ToolStore, activate;"
        f" a = activate(ToolStore(Path({str(store.root)!r})), image='2020.1.1');"
        " import yt_dlp, yt_dlp.version as v; print(a.version, v.__version__, yt_dlp.MARK, yt_dlp.__file__)"
    )

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)

    assert done.returncode == 0, done.stderr
    version, imported, mark, where = done.stdout.split(maxsplit=3)
    assert (version, imported, mark) == ("2099.1.1", "2099.1.1", "1") and Path(where.strip()).parts[:-2] == wheel.parts


@pytest.mark.parametrize("image", ["2099.1.1", "2100.1.1"])
def test_a_start_ignores_a_stored_copy_that_the_image_has_caught_up_with(
    tmp_path: Path, clean_path: None, image: str, caplog: pytest.LogCaptureFixture
) -> None:
    store, _ = staged(tmp_path, "2099.1.1")
    before = list(sys.path)

    with caplog.at_level(logging.INFO, logger=tools.log.name):
        active = activate(store, image=image)

    assert active is None and sys.path == before
    assert "not older" in caplog.text


def test_no_pointer_means_the_images_own_copy(tmp_path: Path, clean_path: None) -> None:
    before = list(sys.path)

    assert activate(ToolStore(tmp_path / "nothing"), image="2026.10.21") is None
    assert sys.path == before


def test_a_missing_or_partial_wheel_costs_one_log_line_and_not_the_start(
    tmp_path: Path, clean_path: None, caplog: pytest.LogCaptureFixture
) -> None:
    before = list(sys.path)

    store, wheel = staged(tmp_path)
    wheel.write_bytes(wheel.read_bytes()[:50])  # an interrupted write
    with caplog.at_level(logging.WARNING, logger=tools.log.name):
        assert activate(store, image="2026.10.21") is None
    assert "does not match" in caplog.text

    caplog.clear()
    store, wheel = staged(tmp_path)
    wheel.unlink()  # a folder copied without its wheels
    with caplog.at_level(logging.WARNING, logger=tools.log.name):
        assert activate(store, image="2026.10.21") is None
    assert "missing" in caplog.text
    assert sys.path == before


def test_a_pointer_that_cannot_be_used_is_removed_so_that_nothing_waits_for_it_and_the_next_check_fetches_it_again(
    tmp_path: Path, clean_path: None
) -> None:
    store, wheel = staged(tmp_path)
    wheel.write_bytes(b"cut short")

    assert activate(store, image="2026.10.21") is None

    assert not store.pointer_file.exists() and store.read_pointer() is None
    assert list(store.wheels.iterdir()) == [], "and its wheel, which is no use to anybody now"


@pytest.mark.parametrize("image", ["2099.1.1", "2100.1.1"])
def test_a_pointer_the_image_has_caught_up_with_is_removed_too(tmp_path: Path, clean_path: None, image: str) -> None:
    store, _ = staged(tmp_path, "2099.1.1")

    assert activate(store, image=image) is None

    assert not store.pointer_file.exists()


def test_a_start_that_cannot_use_the_pointer_because_yt_dlp_is_already_imported_leaves_it_alone(
    tmp_path: Path, clean_path: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = staged(tmp_path)
    monkeypatch.setitem(sys.modules, "yt_dlp", sys)

    assert activate(store, image="2026.10.21") is None

    assert store.pointer_file.exists(), "the copy is fine; it is this process that cannot take it"


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        json.dumps({"version": "2099.1.1"}),
        json.dumps({"version": "2099.1.1", "wheel": "../../etc/x.whl", "sha256": "x"}),
        json.dumps({"version": "2099.1.1", "wheel": "yt_dlp.exe", "sha256": "x"}),
        json.dumps({"version": "soon", "wheel": "yt_dlp-soon-py3-none-any.whl", "sha256": "x"}),
    ],
)
def test_a_pointer_that_is_garbage_or_points_out_of_the_folder_is_ignored(tmp_path: Path, clean_path: None, content: str) -> None:
    store = ToolStore(tmp_path)
    store.pointer_file.write_text(content, encoding="utf-8")
    before = list(sys.path)

    assert activate(store, image="2026.10.21") is None
    assert sys.path == before
    assert not store.pointer_file.exists(), "a pointer nobody can use is not kept"


def test_when_yt_dlp_is_already_imported_the_copy_in_use_is_kept(
    tmp_path: Path, clean_path: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = staged(tmp_path)
    monkeypatch.setitem(sys.modules, "yt_dlp", sys)
    before = list(sys.path)

    assert activate(store, image="2026.10.21") is None
    assert sys.path == before


def test_the_running_version_is_the_stored_one_or_the_images(tmp_path: Path, clean_path: None) -> None:
    store, _ = staged(tmp_path)
    active = activate(store, image="2026.10.21")

    assert tools.running_version(active) == "2099.1.1"
    assert tools.running_version(None) == (tools.image_version() or "unknown")
