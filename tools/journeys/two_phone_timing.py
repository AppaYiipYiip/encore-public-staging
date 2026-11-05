"""two_phone_timing.py A_SERIAL B_SERIAL TAP_X TAP_Y TEXT [TIMEOUT_S]

Journey 4 (docs/history/reviews-2026-10-31.md#audit): the same person on two phones. Taps one point on phone A (the last step of an action, such as "Create" or the
heart) and says how long until TEXT shows on phone B's screen, which is polled with a screen dump. Both phones must already be on the screens
where the change will show (B on the list that will gain the item). The dump itself takes about a second, so the time is an upper bound
(at most about 1.5 s too long). Never prints anything secret; the text is what you typed, so choose a non-secret name.

Run with `python -I`; adb is `C:\\dev\\android-sdk\\platform-tools\\adb.exe`.
"""
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ADB = r"C:\dev\android-sdk\platform-tools\adb.exe"


def adb(serial, *args):
    return subprocess.run([ADB, "-s", serial, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout


def screen_texts(serial):
    out = adb(serial, "exec-out", "uiautomator", "dump", "/dev/tty")
    i, j = out.find("<?xml"), out.rfind("</hierarchy>")
    if i < 0 or j < 0:
        return None
    root = ET.fromstring(out[i : j + len("</hierarchy>")])
    return [(n.get("text") or "") + " | " + (n.get("content-desc") or "") for n in root.iter("node")]


def main():
    a, b, x, y, text = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
    timeout = float(sys.argv[6]) if len(sys.argv) > 6 else 60.0
    before = screen_texts(b) or []
    if any(text in line for line in before):
        print(f"already on B before the action: choose a text that is not there yet ({text!r})")
        sys.exit(2)
    t0 = time.time()
    adb(a, "shell", "input", "tap", x, y)
    t_tap = time.time()
    polls = 0
    while time.time() - t0 < timeout:
        polls += 1
        lines = screen_texts(b)
        if lines and any(text in line for line in lines):
            now = time.time()
            print(f"seen on B {now - t_tap:.1f} s after the tap on A ({polls} dumps; each dump costs about 1 s, so this is an upper bound)")
            return
    print(f"NOT seen on B within {timeout:.0f} s")
    sys.exit(1)


main()
