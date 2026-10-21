"""Does this account really work? A check the owner can press (and that runs by itself right after signing in) (docs/50).

Two small yt-dlp runs with the account's saved sign-in, no download:

1. the account's own watch history (YouTube refuses it to anybody not signed in): proves YouTube recognises the sign-in;
2. one ordinary song, as the server would fetch it: proves the server can *fetch as this account* (this is the step that failed with
   "The page needs to be reloaded" on 2026-10-18, when the service had no JavaScript runtime to solve the player's puzzles).

The answer is a sentence for the owner, never yt-dlp's own words.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

#: A song that is on YouTube Music and will stay (any public, well-known track would do).
SONG = "https://music.youtube.com/watch?v=dQw4w9WgXcQ"

Runner = Callable[[list[str], int], "subprocess.CompletedProcess"]


def _run(argv: list[str], timeout: int) -> "subprocess.CompletedProcess":
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def check_account(binary: str, cookie_file: Path, *, run: Runner = _run, timeout: int = 90) -> dict:
    """`{"ok": bool, "login": bool, "fetch": bool, "message": str}`."""
    cookies = ["--cookies", str(cookie_file)]
    try:
        history = run([binary, "--no-warnings", *cookies, "--flat-playlist", "--playlist-items", "1", "--print", "%(id)s", ":ythis"], timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "login": False, "fetch": False, "message": "YouTube did not answer in time. Try again in a moment."}
    login = history.returncode == 0
    if not login:
        text = (history.stderr or "").lower()
        if "login details are needed" in text or "sign in" in text or "authentication" in text:
            return {"ok": False, "login": False, "fetch": False,
                    "message": "YouTube does not recognise this sign-in any more. Sign in again."}
        return {"ok": False, "login": False, "fetch": False, "message": "Could not ask YouTube just now. Try again in a moment."}
    try:
        song = run([binary, "--no-warnings", "--no-playlist", *cookies, "-s", "--print", "%(title)s", SONG], timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "login": True, "fetch": False, "message": "Signed in, but YouTube did not answer in time. Try again in a moment."}
    if song.returncode == 0:
        return {"ok": True, "login": True, "fetch": True, "message": "Works. YouTube accepts this account for fetching songs."}
    text = (song.stderr or "").lower()
    if "not a bot" in text or "sign in to confirm" in text:
        reason = "YouTube is asking this account to prove it is a person."
    elif "needs to be reloaded" in text or "requested format is not available" in text or "javascript" in text:
        reason = "this server could not solve YouTube's player (it needs a newer songs service)."
    else:
        reason = "YouTube did not let it fetch a song."
    return {"ok": False, "login": True, "fetch": False, "message": f"Signed in, but {reason}"}
