"""Opens every state of the admin website in a real (headless) browser and fails on any error in its console.

    python -m tests.check_pages

The unit tests never run the page's JavaScript, so a typo in it would pass all of them (it did once: an unescaped apostrophe made
every page blank). This is the check that would have caught it. It needs Chrome, Chromium, Edge or Brave on the machine (the
environment variable BROWSER names one); without any it says so and exits 0.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

STATES = ["empty", "signed", "trouble", "two", "preparing", "waiting", "signed_in", "failed"]
CANDIDATES = [
    os.environ.get("BROWSER", ""),
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "chromium", "chromium-browser", "google-chrome", "brave-browser",
]


def find_browser() -> str | None:
    for candidate in CANDIDATES:
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return candidate
    return None


def main() -> int:
    browser = find_browser()
    if browser is None:
        print("no browser here: the pages were not opened")
        return 0
    port = 8898
    failures = 0
    for state in STATES + ["logged-out"]:
        argv = [sys.executable, "-m", "tests.preview", "--state", "signed" if state == "logged-out" else state, "--port", str(port), "--https"]
        if state == "logged-out":
            argv.append("--logged-out")
        server = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=Path(__file__).resolve().parent.parent)
        time.sleep(3)
        try:
            for route in ("youtube", "today", "people", "quality", "recs", "parts"):
                done = subprocess.run(
                    [browser, "--headless=new", "--disable-gpu", "--ignore-certificate-errors", "--enable-logging=stderr", "--v=0",
                     "--virtual-time-budget=8000", "--dump-dom", f"https://127.0.0.1:{port}/#/{route}"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, check=False)
                errors = [line for line in done.stderr.splitlines() if "CONSOLE" in line and ("Uncaught" in line or "rror" in line)]
                blank = '<div id="app"></div>' in done.stdout
                if errors or blank:
                    failures += 1
                    print(f"FAIL {state}/{route}: {'blank page; ' if blank else ''}{errors[:2]}")
                else:
                    print(f"ok   {state}/{route}")
        finally:
            server.terminate()
            server.wait(10)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
