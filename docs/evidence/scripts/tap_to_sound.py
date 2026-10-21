"""Tap a screen point, then poll the media session until the given title is PLAYING. Prints elapsed seconds.

usage: python -I tap_to_sound.py X Y TITLE_SUBSTRING [timeout_s]
"""
import re
import subprocess
import sys
import time

ADB = r"C:\dev\android-sdk\platform-tools\adb.exe"
x, y, want = sys.argv[1], sys.argv[2], sys.argv[3].lower()
limit = float(sys.argv[4]) if len(sys.argv) > 4 else 120


def media():
    out = subprocess.run([ADB, "shell", "dumpsys", "media_session"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    state = re.search(r"state=PlaybackState \{state=(\w+)", out)
    desc = re.search(r"description=([^,\n]{0,70})", out)
    pos = re.search(r"position=(\d+)", out)
    return (state.group(1) if state else None, desc.group(1) if desc else "", int(pos.group(1)) if pos else -1)


start = time.time()
subprocess.run([ADB, "shell", "input", "tap", x, y])
seen = None
while time.time() - start < limit:
    st, desc, pos = media()
    t = time.time() - start
    if want in desc.lower() and seen is None:
        seen = t
        print(f"{t:6.1f}s title shown: {desc!r} state={st}")
    if want in desc.lower() and st in ("3", "PLAYING") and pos > 0:
        print(f"{t:6.1f}s PLAYING (position {pos} ms)")
        break
    time.sleep(0.3)
else:
    st, desc, pos = media()
    print(f"timeout after {limit}s: state={st} desc={desc!r} pos={pos}")
