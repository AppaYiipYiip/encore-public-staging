"""The Host's time zone (`ENCORE_TIME_ZONE`): what "today" means on the admin Home, how the installer finds the computer's zone, and that a wrong value never stops the server.

The server half only: the pages that would let a Host change it are W-09/W-10, still to be approved. Until then the installer writes the computer's own zone once, and the Host may edit the settings file.
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from encore_server.config import Settings, clean_time_zone
from encore_server.routes.admin_health import local_midnight_ms, zone_name
from tests.test_deploy_scripts import BASH, DEPLOY

INSTALL = (DEPLOY / "install.sh").read_text(encoding="utf-8")


def at(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()


# ---------------------------------------------------------------------------------------------------------------------- the setting


def test_a_zone_the_server_knows_is_kept_and_nothing_is_empty_utc() -> None:
    assert clean_time_zone("Europe/Paris") == "Europe/Paris"
    assert clean_time_zone("  Asia/Kolkata \n") == "Asia/Kolkata"
    assert clean_time_zone("") == "UTC" and clean_time_zone("   ") == "UTC"


@pytest.mark.parametrize("wrong", ["Nowhere/Land", "../../etc/passwd", "Europe/Paris; rm -rf /", "CET5CEST", "\x00", "a" * 400])
def test_a_zone_that_cannot_be_loaded_is_utc_with_one_line_in_the_log(wrong: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="encore_server.config"):
        assert clean_time_zone(wrong) == "UTC"
    assert any("not a time zone" in r.message for r in caplog.records), "the Host is told in the log, the server keeps running"


def test_the_settings_read_the_zone_from_the_environment() -> None:
    assert Settings.from_env({"ENCORE_TIME_ZONE": "Europe/Paris"}).time_zone == "Europe/Paris"
    assert Settings.from_env({}).time_zone == "UTC"
    assert Settings.from_env({"ENCORE_TIME_ZONE": "Mars/Olympus"}).time_zone == "UTC"


def test_zone_data_comes_with_the_server_not_with_the_operating_system() -> None:
    """A slim container image may have no /usr/share/zoneinfo: the `tzdata` package is a dependency, so a zone loads on any image (the built image is checked by the real-install CI job)."""
    import importlib.metadata

    assert importlib.metadata.version("tzdata")
    assert ZoneInfo("Pacific/Kiritimati").utcoffset(datetime(2026, 11, 27)) is not None


# ---------------------------------------------------------------------------------------------------------------------- "today"


@pytest.mark.parametrize(
    ("zone", "now", "midnight"),
    [
        ("UTC", "2026-11-27T13:20:00", "2026-11-27T00:00:00"),
        ("Europe/Paris", "2026-11-27T13:20:00", "2026-11-26T23:00:00"),  # CET, UTC+1
        ("Europe/Paris", "2026-07-15T13:20:00", "2026-07-14T22:00:00"),  # CEST, UTC+2
        ("Europe/Paris", "2026-03-29T12:00:00", "2026-03-28T23:00:00"),  # the day the clocks go forward: midnight was still CET
        ("Europe/Paris", "2026-10-25T12:00:00", "2026-10-24T22:00:00"),  # the day they go back: midnight was CEST
        ("Asia/Kolkata", "2026-11-27T03:00:00", "2026-11-26T18:30:00"),  # a half-hour offset: 08:30 there
        ("Pacific/Kiritimati", "2026-11-27T11:00:00", "2026-11-27T10:00:00"),  # UTC+14: already the 28th there
        ("America/Los_Angeles", "2026-11-27T05:00:00", "2026-11-26T08:00:00"),  # still the 26th there (21:00 PST)
    ],
)
def test_today_starts_at_midnight_in_the_hosts_zone(zone: str, now: str, midnight: str) -> None:
    assert local_midnight_ms(at(now), zone) == int(at(midnight) * 1000)


def test_today_has_never_lasted_more_than_a_day_and_a_bit_nor_started_in_the_future() -> None:
    for zone in ("UTC", "Europe/Paris", "Asia/Kolkata", "Pacific/Kiritimati", "America/St_Johns", "Australia/Lord_Howe"):
        for day in (
            "2026-03-28T23:30:00",
            "2026-03-29T00:30:00",
            "2026-04-05T01:30:00",
            "2026-10-03T16:00:00",
            "2026-10-25T00:30:00",
        ):
            now = at(day)
            start = local_midnight_ms(now, zone) / 1000
            assert start <= now and now - start <= 25 * 3600, (zone, day)


def test_the_default_is_utc_as_it_was() -> None:
    now = at("2026-11-27T13:20:00")
    assert local_midnight_ms(now) == local_midnight_ms(now, "UTC")


def test_home_names_the_zone_the_way_people_say_it() -> None:
    assert zone_name("Europe/Paris", at("2026-11-27T12:00:00")) == "CET"
    assert zone_name("Europe/Paris", at("2026-07-15T12:00:00")) == "CEST"
    assert zone_name("UTC") == "UTC"


# ---------------------------------------------------------------------------------------------------------------------- the installer


def function(name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{.*?^\}}\n", INSTALL, re.S | re.M)
    assert match is not None, name
    return match.group(0)


def run(script: str, *, path: str | None = None) -> subprocess.CompletedProcess[str]:
    assert BASH is not None
    env = {"PATH": path} if path is not None else None
    return subprocess.run([BASH, "-c", script], capture_output=True, text=True, check=False, timeout=60, env=env)


def fake_commands(tmp: Path, **commands: str) -> str:
    """A folder of made-up commands in front of the real PATH, so that a test says what the computer answers."""
    folder = tmp / "bin"
    folder.mkdir()
    for name, body in commands.items():
        script = folder / name
        script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        script.chmod(0o755)
    return f"{folder}:/usr/bin:/bin"


@pytest.mark.skipif(BASH is None, reason="needs bash")
@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Europe/Paris", "Europe/Paris"),
        ("Etc/UTC", "Etc/UTC"),
        ("America/Argentina/Buenos_Aires", "America/Argentina/Buenos_Aires"),
    ],
)
def test_the_installer_takes_the_computers_zone_from_timedatectl(tmp_path: Path, answer: str, expected: str) -> None:
    path = fake_commands(tmp_path, timedatectl=f"echo '{answer}'")
    result = run("set -Eeuo pipefail\n" + function("detect_time_zone") + "\ndetect_time_zone", path=path)
    assert result.returncode == 0 and result.stdout == expected


@pytest.mark.skipif(BASH is None, reason="needs bash")
@pytest.mark.parametrize("answer", ["Europe/Paris; rm -rf /", "$(reboot)", "a b", "Europe/Paris`id`", ""])
def test_the_installer_never_writes_a_zone_with_a_character_a_shell_could_use(tmp_path: Path, answer: str) -> None:
    path = fake_commands(tmp_path, timedatectl=f"printf '%s' '{answer}'", cat="exit 1", readlink="exit 1")
    result = run("set -Eeuo pipefail\n" + function("detect_time_zone") + "\ndetect_time_zone", path=path)
    assert result.returncode == 1 and result.stdout == ""


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_the_installer_writes_the_zone_once_and_keeps_what_the_host_edited(tmp_path: Path) -> None:
    env_line = next(line for line in INSTALL.splitlines() if line.startswith("env_value()"))
    (tmp_path / ".env").write_text("ENCORE_PORT=4533\n", encoding="utf-8")
    path = fake_commands(tmp_path, timedatectl="echo 'Europe/Paris'")
    script = f"set -Eeuo pipefail\nDIR='{tmp_path}'\n{env_line}\n{function('detect_time_zone')}\n{function('ensure_time_zone')}\nensure_time_zone\nensure_time_zone\n"

    assert run(script, path=path).returncode == 0
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert text.count("ENCORE_TIME_ZONE=") == 1 and "ENCORE_TIME_ZONE=Europe/Paris" in text

    (tmp_path / ".env").write_text("ENCORE_TIME_ZONE=Asia/Tokyo\n", encoding="utf-8")  # the Host's own choice
    assert run(script, path=path).returncode == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "ENCORE_TIME_ZONE=Asia/Tokyo\n"


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_a_computer_that_cannot_say_its_zone_gets_no_line_and_the_install_goes_on(tmp_path: Path) -> None:
    env_line = next(line for line in INSTALL.splitlines() if line.startswith("env_value()"))
    (tmp_path / ".env").write_text("ENCORE_PORT=4533\n", encoding="utf-8")
    path = fake_commands(tmp_path, timedatectl="exit 1", cat="exit 1", readlink="exit 1")
    script = f"set -Eeuo pipefail\nDIR='{tmp_path}'\n{env_line}\n{function('detect_time_zone')}\n{function('ensure_time_zone')}\nensure_time_zone\n"

    assert run(script, path=path).returncode == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "ENCORE_PORT=4533\n"


def test_the_compose_file_hands_the_zone_to_the_server() -> None:
    assert "ENCORE_TIME_ZONE: ${ENCORE_TIME_ZONE:-}" in (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
