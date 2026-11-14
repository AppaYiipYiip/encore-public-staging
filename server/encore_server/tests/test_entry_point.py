"""AUDIT B-57: `python -m encore_server` with a word it does not know must not start the server.

Before, everything that was not `setup` or `backup` fell through to `uvicorn.run`: `--help`, `restore` or a typo, typed in the container of a live
install, ran the migrations and the scheduler on the live database and then failed to bind a port the real server holds (on a stopped install it
started a second server). Only no argument runs the server (the container's command)."""

from __future__ import annotations

from typing import Any

import pytest

from encore_server import __main__ as entry


def _nothing_may_start(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the server was started")

    monkeypatch.setattr(entry.uvicorn, "run", boom)
    monkeypatch.setattr(entry, "create_app", boom)
    monkeypatch.setattr(entry.Settings, "from_env", boom)


@pytest.mark.parametrize("word", ["--help", "-h", "help"])
def test_a_request_for_help_names_the_commands_and_starts_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], word: str
) -> None:
    _nothing_may_start(monkeypatch)

    with pytest.raises(SystemExit) as stop:
        entry.main([word])

    assert stop.value.code == 0
    out = capsys.readouterr().out
    assert "setup" in out and "backup" in out


@pytest.mark.parametrize("args", [["restore"], ["--halp"], ["setpu"], ["serve", "now"]])
def test_a_word_it_does_not_know_is_refused_with_the_commands_and_starts_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    _nothing_may_start(monkeypatch)

    with pytest.raises(SystemExit) as stop:
        entry.main(args)

    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert args[0] in err, "it says which word it did not understand"
    assert "setup" in err and "backup" in err
