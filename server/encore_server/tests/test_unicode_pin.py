"""The Unicode version the fold is pinned to is a REFUSAL to start, not a hope (P2-25 slices 2 and 3; the advisor's requirement of 15 Nov, sharpened on 16 Nov).

A stored `norm_key` is a function of the Unicode data of the Python that made it: a code point that is a letter in one version and a gap in another changes the
words of a title (the 622 CJK Extension I ideographs of Unicode 15.1.0 are letters there and gaps in the image's 15.0.0). A server that only refused to REWRITE the
keys would go on serving and writing interpreter-dependent keys that nothing ever re-checks: a permanent drift. So the pin (`textnorm.UNICODE_VERSION`, 15.0.0, what
`python:3.12-slim` ships) is held in five places, all here:

1. the IMAGE, the WORKFLOW and `requires-python` (files: they fail on any interpreter the day somebody moves one of them alone);
2. the SERVER: `create_app` and the server command refuse to start on any other Unicode, and say which Python is needed and how to get it;
3. the key repair itself (`keyrepair.repair`), a second layer for any other caller;
4. the TEST RUN: `conftest.py` stops the whole session before the first test (nobody tests on another Unicode by accident).

There is NO environment variable, flag or setting that turns the guard off: that would be the easy choice that costs later (a Host who sets it to get past the message
stores keys the next image cannot read). What a Python bump costs, and when this goes, is in `docs/18-data-model-and-migration.md` (the Unicode pin).
"""

# ruff: noqa: F811 - `old_world` is the fixture of tests/test_keyrepair.py, imported to be used
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest
from packaging.specifiers import SpecifierSet

from encore_server import __main__ as entry
from encore_server import keyrepair, textnorm
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database
from tests import conftest as suite
from tests.test_keyrepair import FAIRUZ, key_of, old_world, revision  # noqa: F401 - the fixture

ROOT = Path(__file__).resolve().parents[3]
OTHER_UNICODES = ["15.1.0", "16.0.0", "14.0.0", ""]


def _minor(text: str) -> str:
    match = re.search(r"3\.\d+", text)
    assert match, text
    return match.group(0)


def _pinned_minor() -> str:
    return next(minor for minor, version in textnorm.UNICODE_OF_PYTHON.items() if version == textnorm.UNICODE_VERSION)


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# 1. the files that name a Python


def test_the_image_runs_the_python_that_ships_the_pinned_unicode() -> None:
    first_line = (ROOT / "server" / "encore_server" / "Dockerfile").read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("FROM python:"), first_line
    minor = _minor(first_line)
    assert textnorm.UNICODE_OF_PYTHON.get(minor) == textnorm.UNICODE_VERSION, (
        f"The image is {first_line!r}: Python {minor} ships Unicode {textnorm.UNICODE_OF_PYTHON.get(minor)!r} and the fold is pinned to "
        f"{textnorm.UNICODE_VERSION!r}. Move the image, server.yml, requires-python, textnorm.UNICODE_VERSION, the fixture and the phone's table together (one pull request)."
    )


@pytest.mark.parametrize("name", ["server.yml", "server-image.yml"])
def test_every_workflow_that_runs_the_server_tests_runs_the_python_that_ships_the_pinned_unicode(name: str) -> None:
    """The conftest stops a run on any other Python, so a workflow on another Python would fail at once (and a workflow that only builds would say nothing)."""
    workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    versions = re.findall(r"python-version:\s*'?(3\.\d+)'?", workflow)
    assert versions, f"{name} names no python-version"
    for minor in versions:
        assert textnorm.UNICODE_OF_PYTHON.get(minor) == textnorm.UNICODE_VERSION, f"{name} runs Python {minor}"


def test_the_integration_test_image_runs_the_python_that_ships_the_pinned_unicode() -> None:
    lines = (ROOT / "server" / "encore_server" / "tests" / "integration" / "Dockerfile").read_text(encoding="utf-8").splitlines()
    base = next(line for line in lines if line.startswith("FROM "))
    assert base.startswith("FROM python:"), base
    assert textnorm.UNICODE_OF_PYTHON.get(_minor(base)) == textnorm.UNICODE_VERSION, base


def test_requires_python_accepts_only_pythons_that_ship_the_pinned_unicode() -> None:
    """`pip install` on a Python 3.13 must fail at the install, not at the first start: `requires-python` is the earliest of the refusals."""
    pyproject = (ROOT / "server" / "encore_server" / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^requires-python\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert match, "pyproject.toml has no requires-python"
    spec = SpecifierSet(match.group(1))
    for minor, version in textnorm.UNICODE_OF_PYTHON.items():
        assert spec.contains(f"{minor}.0") == (version == textnorm.UNICODE_VERSION), (
            f"requires-python = {match.group(1)!r} and Python {minor} (Unicode {version}): the pin is {textnorm.UNICODE_VERSION}"
        )
    assert spec.contains(f"{_pinned_minor()}.99"), "every patch release of the pinned Python is accepted"


def test_the_pin_is_the_one_every_file_that_names_it_says() -> None:
    table = (ROOT / "app" / "lib" / "domain" / "text_fold_table.g.dart").read_text(encoding="utf-8")
    assert f"kTextFoldUnidataVersion = '{textnorm.UNICODE_VERSION}'" in table


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the message and the check


def test_the_python_that_runs_these_tests_has_the_pinned_unicode() -> None:
    """The conftest stopped the session before this line if it did not; this is the plain statement of what the whole suite relies on."""
    assert unicodedata.unidata_version == textnorm.UNICODE_VERSION == textnorm.running_unicode()


@pytest.mark.parametrize("running", OTHER_UNICODES)
def test_the_message_says_exactly_which_python_is_needed_and_how_to_get_it(running: str) -> None:
    message = textnorm.unicode_refusal(running)
    minor = _pinned_minor()
    assert minor == "3.12"
    assert running in message and textnorm.UNICODE_VERSION in message
    assert f"Python {minor}" in message, "the Python that is needed"
    assert f"python:{minor}-slim" in message, "the image the project ships already is that Python"
    assert "uv python install" in message and "python.org" in message, "two ways to get it that need no knowledge of this project"
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/](?!/)", message), (
        "no path of any developer's machine in a message the Host reads"
    )
    if running in {v for v in textnorm.UNICODE_OF_PYTHON.values()}:
        other = next(m for m, v in textnorm.UNICODE_OF_PYTHON.items() if v == running)
        assert f"Python {other}" in message, "a Python the project has met is named"


def test_the_pinned_unicode_passes_and_every_other_raises() -> None:
    textnorm.require_pinned_unicode(textnorm.UNICODE_VERSION)
    for running in OTHER_UNICODES:
        with pytest.raises(textnorm.UnicodeVersionError) as stop:
            textnorm.require_pinned_unicode(running)
        assert str(stop.value) == textnorm.unicode_refusal(running)


def test_there_is_no_way_to_switch_the_guard_off() -> None:
    """No environment variable, setting or argument: the check takes only the version it looks at, and nothing in `Settings` or the environment names it."""
    import inspect

    assert list(inspect.signature(textnorm.require_pinned_unicode).parameters) == ["running"]
    assert "unicode" not in " ".join(Settings.__dataclass_fields__).lower()
    for function in (textnorm.require_pinned_unicode, textnorm.running_unicode, textnorm.unicode_refusal):
        assert not {"environ", "getenv", "os"} & set(function.__code__.co_names), function.__name__


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# 2. the server refuses to start


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        workers=False,
    )


@pytest.mark.parametrize("running", OTHER_UNICODES)
def test_create_app_refuses_to_start_and_creates_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, running: str) -> None:
    monkeypatch.setattr(textnorm, "running_unicode", lambda: running)
    settings = _settings(tmp_path)
    with pytest.raises(textnorm.UnicodeVersionError) as stop:
        create_app(settings)
    assert str(stop.value) == textnorm.unicode_refusal(running)
    assert not settings.db_path.exists() and not settings.data_dir.exists(), (
        "not a database, not a folder: the refusal comes before anything is opened"
    )


def test_create_app_starts_on_the_pinned_unicode(tmp_path: Path) -> None:
    assert create_app(_settings(tmp_path)) is not None


@pytest.mark.parametrize("running", ["15.1.0", "16.0.0"])
def test_the_server_command_prints_the_message_and_exits_without_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], running: str
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("something started although the Unicode is not the pin")

    monkeypatch.setattr(textnorm, "running_unicode", lambda: running)
    monkeypatch.setattr(entry.uvicorn, "run", boom)
    monkeypatch.setattr(entry, "create_app", boom)
    monkeypatch.setattr(entry.Settings, "from_env", boom)
    monkeypatch.setattr(entry, "activate", boom)

    with pytest.raises(SystemExit) as stop:
        entry.main([])

    assert stop.value.code == 1
    err = capsys.readouterr().err
    assert textnorm.unicode_refusal(running) in err and "Traceback" not in err, "the message, not a stack trace"


def test_the_backup_command_is_not_guarded_it_is_a_rescue_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """`encore backup` copies the databases and writes no key: it must keep working on any Python the Host has."""
    monkeypatch.setattr(textnorm, "running_unicode", lambda: "16.0.0")
    import encore_server.backup as backup_command

    monkeypatch.setattr(backup_command, "command", lambda args: 0)
    with pytest.raises(SystemExit) as stop:
        entry.main(["backup"])
    assert stop.value.code == 0


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# 3. the key repair, a second layer for any caller that is not `create_app`


@pytest.mark.parametrize("running", ["15.1.0", "16.0.0"])
def test_a_python_with_another_unicode_makes_the_repair_refuse_and_write_nothing(
    old_world: Database, monkeypatch: pytest.MonkeyPatch, running: str
) -> None:
    monkeypatch.setattr(textnorm, "running_unicode", lambda: running)
    before = key_of(old_world, FAIRUZ)
    with pytest.raises(textnorm.UnicodeVersionError):
        keyrepair.repair(old_world)
    assert key_of(old_world, FAIRUZ) == before and revision(old_world) is None
    assert old_world.copies("before-key-rewrite") == [], "no copy either"


def test_the_pinned_python_rewrites_and_records_the_unicode_it_did_it_under(old_world: Database) -> None:
    report = keyrepair.repair(old_world)
    assert report.ran is True
    with old_world.read() as conn:
        stored = conn.execute("SELECT value FROM setting WHERE key = 'textnorm_unicode'").fetchone()
    assert stored is not None and stored["value"] == textnorm.UNICODE_VERSION


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# 4. the test run


@pytest.mark.parametrize("running", OTHER_UNICODES)
def test_the_conftest_stops_the_whole_run_before_the_first_test_with_the_same_message(
    monkeypatch: pytest.MonkeyPatch, running: str
) -> None:
    monkeypatch.setattr(textnorm, "running_unicode", lambda: running)
    with pytest.raises(pytest.exit.Exception) as stop:
        suite.pytest_configure(None)  # type: ignore[arg-type]
    assert textnorm.unicode_refusal(running) in str(stop.value)
    assert stop.value.returncode not in (0, None)


def test_the_conftest_lets_the_pinned_unicode_through() -> None:
    suite.pytest_configure(None)  # type: ignore[arg-type]
