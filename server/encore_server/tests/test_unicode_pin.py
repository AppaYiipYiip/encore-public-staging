"""The Unicode version the fold is pinned to is guarded in three places (P2-25 slices 2 and 3; the advisor's requirement of 15 Nov and the lead's of 16 Nov).

A stored `norm_key` is a function of the Unicode data of the Python that made it: a code point that is a letter in one version and a gap in another changes the
words of a title. The pin (`textnorm.UNICODE_VERSION`, 15.0.0) is what `python:3.12-slim` and `server.yml` ship. Three guards, because one cannot cover all three
ways it goes wrong:

1. the IMAGE and the WORKFLOW (files, so they fail on any interpreter the day somebody bumps the base image alone: the slice-1 trap, "words() would read 622 CJK
   Extension I ideographs as letters with no test red");
2. the INTERPRETER that runs the tests (fails on any other Unicode; the one listed newer version, 15.1.0 on a developer's Python 3.13, skips with a visible reason
   because it ADDS 627 code points and nothing else, run, and the corpus tests skip exactly those). **A deviation from "fail on any difference", named in the
   pull request**: a hard failure would stop the pre-commit gate on the 3.13 development venv; the production guard below has no such allowance;
3. the START-UP: a server on a Python with ANY other Unicode (15.1.0 included) REFUSES to write or rewrite the stored keys and says so at ERROR level on every
   start (it never stops: it serves). `conftest.py` shows every other test the pinned version; the tests here run against the real one (`real_unicode`).
"""

# ruff: noqa: F811 - `old_world` is the fixture of tests/test_keyrepair.py, imported to be used
from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

import pytest

from encore_server import keyrepair, textnorm
from encore_server.db import Database
from tests.test_keyrepair import FAIRUZ, key_of, old_world, revision  # noqa: F401 - the fixture

pytestmark = pytest.mark.real_unicode

ROOT = Path(__file__).resolve().parents[3]


def _minor(text: str) -> str:
    match = re.search(r"3\.\d+", text)
    assert match, text
    return match.group(0)


def test_the_image_runs_the_python_that_ships_the_pinned_unicode() -> None:
    first_line = (ROOT / "server" / "encore_server" / "Dockerfile").read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("FROM python:"), first_line
    minor = _minor(first_line)
    assert textnorm.UNICODE_OF_PYTHON.get(minor) == textnorm.UNICODE_VERSION, (
        f"The image is {first_line!r}: Python {minor} ships Unicode {textnorm.UNICODE_OF_PYTHON.get(minor)!r} and the fold is pinned to "
        f"{textnorm.UNICODE_VERSION!r}. Move the image, server.yml, textnorm.UNICODE_VERSION, the fixture and the phone's table together (one pull request)."
    )


def test_the_server_workflow_runs_the_python_that_ships_the_pinned_unicode() -> None:
    workflow = (ROOT / ".github" / "workflows" / "server.yml").read_text(encoding="utf-8")
    versions = re.findall(r"python-version:\s*'?(3\.\d+)'?", workflow)
    assert versions, "server.yml names no python-version"
    for minor in versions:
        assert textnorm.UNICODE_OF_PYTHON.get(minor) == textnorm.UNICODE_VERSION, f"server.yml runs Python {minor}"


def test_the_pin_is_the_one_every_file_that_names_it_says() -> None:
    table = (ROOT / "app" / "lib" / "domain" / "text_fold_table.g.dart").read_text(encoding="utf-8")
    assert f"kTextFoldUnidataVersion = '{textnorm.UNICODE_VERSION}'" in table


def test_the_python_that_runs_these_tests_has_the_pinned_unicode_or_a_proven_compatible_one() -> None:
    status = textnorm.unicode_pin_status()
    if status == "compatible":
        pytest.skip(
            f"Unicode {unicodedata.unidata_version} is a development Python (the pin is {textnorm.UNICODE_VERSION}): it only ADDS code points, which the corpus "
            "tests skip; run these tests under Python 3.12 too (CI does)"
        )
    assert status == "pinned", (
        f"This Python has Unicode {unicodedata.unidata_version}; the fold is pinned to {textnorm.UNICODE_VERSION}. Stored keys must never depend on the "
        "interpreter: run Python 3.12, or move the pin on purpose (UNICODE_VERSION, TEXTNORM_REVISION, the fixture, the table and the image together)."
    )


@pytest.mark.parametrize(
    ("running", "status"),
    [("15.0.0", "pinned"), ("15.1.0", "compatible"), ("16.0.0", "other"), ("14.0.0", "other"), ("", "other")],
)
def test_the_status_of_a_unicode_version(running: str, status: str) -> None:
    assert textnorm.unicode_pin_status(running) == status


def test_the_one_compatible_version_is_listed_with_its_proof() -> None:
    """A version is compatible only when the tests that skip its added code points exist: the two lists are one fact."""
    from tests import textfold_corpus

    for newer in textnorm.UNICODE_COMPATIBLE:
        assert (textnorm.UNICODE_VERSION, newer) in textfold_corpus.ASSIGNED_AFTER_PIN


def test_a_python_with_another_unicode_makes_the_rewrite_refuse_and_say_so(
    old_world: Database,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(textnorm, "running_unicode", lambda: "16.0.0")
    before = key_of(old_world, FAIRUZ)
    with caplog.at_level(logging.WARNING, logger="encore_server.keyrepair"):
        report = keyrepair.repair(old_world)
    assert report.refused is True and report.ran is False and report.failed is False and report.backup is None
    assert key_of(old_world, FAIRUZ) == before and revision(old_world) is None
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors and "16.0.0" in errors[0].getMessage() and textnorm.UNICODE_VERSION in errors[0].getMessage()


def test_a_development_python_does_not_rewrite_the_keys_either(
    old_world: Database,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """15.1.0 only ADDS code points, and a test run tolerates it; a server does not. A title with one of the 622 CJK Extension I ideographs is a word there and a gap
    in the image: the key it was stored under must not depend on which Python made it."""
    monkeypatch.setattr(textnorm, "running_unicode", lambda: "15.1.0")
    before = key_of(old_world, FAIRUZ)
    with caplog.at_level(logging.WARNING, logger="encore_server.keyrepair"):
        report = keyrepair.repair(old_world)
    assert report.refused is True and report.ran is False and report.backup is None
    assert key_of(old_world, FAIRUZ) == before and revision(old_world) is None
    assert [r.levelno for r in caplog.records] == [logging.ERROR]
    assert "15.1.0" in caplog.records[0].getMessage() and textnorm.UNICODE_VERSION in caplog.records[0].getMessage()


def test_the_pinned_python_rewrites_and_records_the_unicode_it_did_it_under(
    old_world: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(textnorm, "running_unicode", lambda: textnorm.UNICODE_VERSION)
    report = keyrepair.repair(old_world)
    assert report.ran is True and report.refused is False
    with old_world.read() as conn:
        stored = conn.execute("SELECT value FROM setting WHERE key = 'textnorm_unicode'").fetchone()
    assert stored is not None and stored["value"] == textnorm.UNICODE_VERSION


def test_the_refusal_never_stops_the_server_from_starting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from encore_server.api import create_app
    from encore_server.config import Settings

    monkeypatch.setattr(textnorm, "running_unicode", lambda: "16.0.0")
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        workers=False,
    )
    assert create_app(settings) is not None
