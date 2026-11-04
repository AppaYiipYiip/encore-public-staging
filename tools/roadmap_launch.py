#!/usr/bin/env python3
"""Opening the roadmap board like an app, and making sure only ONE board runs.

* The board opens in its own window with no address bar (a Chromium "app window": Brave, Chrome or Edge), so nobody has to look at or type an address. Where there is
  no such browser it opens a normal tab of the default browser. The address still exists for a bookmark: http://roadmap.localhost:8765/ (the name *.localhost
  always means this computer in Chrome, Brave, Edge and Firefox) or http://127.0.0.1:8765/.
* ONE instance: a second start never opens a second server on another port. If a board already answers on the port it is the same code from the same folder, so
  the new start just opens a window on it; if it is OLD code or ANOTHER folder, the new start refuses and says which window to close. (On 3 Nov 2026 a board still
  running old code wrote a stale file into the plan; two servers on two ports is how that happens.)
"""
from __future__ import annotations

import http.client
import json
import ntpath
import os
import posixpath
import shutil
import subprocess
import sys
import webbrowser

NAME = "roadmap.localhost"
APP_SIZE = "--window-size=1180,900"


def _paths(platform: str):
    """The path rules of the platform being asked about, not of the machine running this code: the logic is then the same on every host and testable on all of them."""
    return ntpath if platform == "win32" else posixpath


def candidates(env: dict[str, str] | None = None, platform: str | None = None, which=shutil.which) -> list[str]:
    """Chromium-based browsers, the owner's own first (ROADMAP_BROWSER), then Brave, Chrome, Edge."""
    env = os.environ if env is None else env
    platform = platform or sys.platform
    pp = _paths(platform)
    out: list[str] = []
    if env.get("ROADMAP_BROWSER"):
        out.append(env["ROADMAP_BROWSER"])
    if platform == "win32":
        roots = [env.get(k, "") for k in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData")]
        for sub in (r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe"):
            out += [pp.join(r, sub) for r in roots if r]
    elif platform == "darwin":
        for app in ("Brave Browser", "Google Chrome", "Microsoft Edge"):
            out.append(f"/Applications/{app}.app/Contents/MacOS/{app}")
    else:
        for exe in ("brave-browser", "brave", "google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            w = which(exe)
            if w:
                out.append(w)
    return out


def find_app_browser(env: dict[str, str] | None = None, platform: str | None = None, exists=os.path.exists, which=shutil.which) -> str | None:
    for c in candidates(env, platform, which):
        if exists(c):
            return c
    return None


def open_board(port: int, app_window: bool = True, env: dict[str, str] | None = None, platform: str | None = None, exists=os.path.exists,
               spawn=subprocess.Popen, tab=webbrowser.open) -> str:
    """Returns a short description of what was opened (for the console and the tests)."""
    exe = find_app_browser(env, platform, exists) if app_window else None
    if exe:
        try:
            spawn([exe, f"--app=http://{NAME}:{port}/", APP_SIZE], close_fds=True)
            return f"app window ({_paths(platform or sys.platform).basename(exe)})"
        except OSError:
            pass                                          # fall through to a plain tab
    tab(f"http://127.0.0.1:{port}/")                      # the numeric address works in every browser
    return "browser tab"


def probe(port: int, timeout: float = 2.0) -> dict | None:
    """Is a roadmap board answering on this port? Its /api/hello (who, which code, which folder), or None when the port is free or some other program owns it."""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request("GET", "/api/hello", headers={"Host": f"127.0.0.1:{port}"})
        r = c.getresponse()
        data = json.loads(r.read() or b"{}")
        return data if isinstance(data, dict) and data.get("board") == "encore-roadmap" else None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        c.close()


def decide_when_port_is_taken(other: dict | None, root: str, code: str, port: int) -> tuple[str, str]:
    """('open', message) when the running board is this very one; ('refuse', message) otherwise. Plain words: the owner reads this in a console window."""
    if other is None:
        return "refuse", (f"Port {port} is used by another program, not by the roadmap board. Close that program, or start this one on another port with:  --port {port + 1}")
    same_root = os.path.normcase(str(other.get("root", ""))) == os.path.normcase(root)
    same_code = other.get("code") == code
    if same_root and same_code:
        return "open", "The board is already running: opening it. (Nothing new was started.)"
    why = []
    if not same_code:
        why.append("it is running OLD code (the files changed after it started)")
    if not same_root:
        why.append(f"it was started from another folder ({other.get('root')})")
    return "refuse", (f"Another roadmap board is already running on port {port} (process {other.get('pid', '?')}) and {' and '.join(why)}. "
                      "Close the window that started it, then start the board again. Nothing was changed.")
