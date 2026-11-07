"""J-03, the honest number: Next presses, and for each the time until the new song is really playing.

The media session says PLAYING at once when Next is pressed (position ~0, the new title) and BUFFERING until the bytes arrive; the old probe took that first PLAYING for
'audible' (found 7 Nov 2026 from the server log). A press is audible here when the session goes BUFFERING -> PLAYING and nothing but PLAYING follows for 0.4 s (an 85 ms blip before a pause is not
audio; the app's own `play.audible` span, P1-06, ends at position 200 ms but is begun only by a tap, not by a skip). It reads the system's own timestamps in logcat
(MediaSessionService state events) and a sampler on the phone that writes the shown title every ~0.15 s, so the report says WHICH song became audible when, and
every pause (a pause nobody asked for is the thing to look for).

    python -I -X utf8 next_timing.py PRESSES SPACING_SECONDS [SERIAL]      (the first press happens after SPACING_SECONDS; the key is KEYCODE_MEDIA_NEXT)
"""
import re
import subprocess
import sys
import time

ADB = r"C:\dev\android-sdk\platform-tools\adb.exe"
presses = int(sys.argv[1])
spacing = float(sys.argv[2])
serial = sys.argv[3] if len(sys.argv) > 3 else "emulator-5554"
LOOP = (
    "while [ -f /data/local/tmp/sess.run ]; do "
    "echo \"$(date +%s.%N) $(dumpsys media_session | grep -A14 'media-session app.encore' | grep -E 'description=' | head -1)\"; "
    "done > /data/local/tmp/sess.log"
)


def adb(*a, bg=False):
    if bg:
        return subprocess.Popen([ADB, "-s", serial, *a], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.run([ADB, "-s", serial, *a], check=False, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


adb("shell", "rm -f /data/local/tmp/sess.run /data/local/tmp/sess.log")
adb("shell", "touch /data/local/tmp/sess.run")
adb("logcat", "-c")
sampler = adb("shell", LOOP, bg=True)
time.sleep(2)
for i in range(presses):
    time.sleep(spacing)
    adb("shell", "input", "keyevent", "87")
time.sleep(10)
adb("shell", "rm -f /data/local/tmp/sess.run")
time.sleep(1.5)
log = adb("logcat", "-d", "-v", "epoch")
samples = []
for line in adb("shell", "cat /data/local/tmp/sess.log").splitlines():
    m = re.match(r"(\d+\.\d+)\s+.*?description=(.*)", line)
    if m:
        samples.append((float(m.group(1)), m.group(2).split(",")[0].strip()))


def title_at(t):
    best = None
    for ts, name in samples:
        if ts <= t:
            best = name
        else:
            break
    return best


keys, states = [], []
for line in log.splitlines():
    m = re.match(r"\s*(\d+\.\d+)\s", line)
    if not m or "MediaSessionService" not in line:
        continue
    t = float(m.group(1))
    if "dispatchMediaKeyEventToSessionAsSystemService" in line and "ACTION_DOWN" in line:
        keys.append(t)
        continue
    s = re.search(r"playbackState=PlaybackState \{state=(\w+)\(\d+\), position=(\d+)", line)
    if s:
        states.append((t, s.group(1), int(s.group(2))))
t0 = keys[0] if keys else (states[0][0] if states else 0)
events = []   # (time, text)
for k in keys:
    events.append((k, "PRESS Next"))
def stays(i):
    """A PLAYING event is audio only when nothing but more PLAYING follows within 0.4 s (an 85 ms blip before a pause is not)."""
    t = states[i][0]
    for t2, st2, _ in states[i + 1:]:
        if t2 - t > 0.4:
            return True
        if st2 != "PLAYING":
            return False
    return True


prev = None
audible = []
for i, (t, st, pos) in enumerate(states):
    if st != prev:
        name = title_at(t)
        if st == "PAUSED":
            events.append((t, f"PAUSED   at {pos} ms, title {name!r}"))
        elif st == "BUFFERING":
            events.append((t, f"BUFFERING (title {name!r})"))
        elif st == "PLAYING":
            real = prev == "BUFFERING" and stays(i)
            if real:
                audible.append((t, pos, name))
            events.append((t, f"{'AUDIBLE ' if real else 'playing '} position {pos} ms (title {name!r})"))
    prev = st
events.sort()
for t, text in events:
    print(f"+{t - t0:7.2f} s  {text}")
print()
for i, k in enumerate(keys):
    nxt = keys[i + 1] if i + 1 < len(keys) else k + 30
    got = [(t, pos, name) for t, pos, name in audible if k < t < nxt]
    if got:
        t, pos, name = got[0]
        print(f"press {i + 1}: audible {t - pos / 1000 - k:.2f} s after the key ({name!r})")
    else:
        print(f"press {i + 1}: NOT audible before the next press / 30 s")
print("last title:", samples[-1][1] if samples else None, "| last states:", states[-3:])
sampler.terminate()
