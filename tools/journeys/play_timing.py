#!/usr/bin/env python3
"""Measures what a person waits for: search for a song, tap it, and time until sound is really coming out (docs/07 section 3).

    python -I play_timing.py "Beach House|Space Song" "Mazzy Star|Fade Into You" ...        (artist|title as people type them)

The device defaults to emulator-5556 (ANDROID_SERIAL overrides). "Audible" means the media session says PLAYING for this song AND the audio
system has a started track (the session alone is not enough: it said PLAYING with no sound on 2026-10-21; its position is not a live clock).
Prints, per song, the seconds from the tap to audible, then the median and the slowest. The songs must be new to the server for the
number to mean "a song nobody has played there"; pick them accordingly and never repeat a song in a series.

It only types a search and taps a result: no password is ever involved (be signed in already).
"""
import os
import re
import statistics
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ADB = r"C:\dev\android-sdk\platform-tools\adb.exe"
SERIAL = os.environ.get("ANDROID_SERIAL", "emulator-5556")


def adb(*args):
    return subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def screen():
    for _ in range(4):
        out = adb("exec-out", "uiautomator", "dump", "/dev/tty")
        i, j = out.find("<?xml"), out.rfind("</hierarchy>")
        if i >= 0 and j > 0:
            found = []
            for n in ET.fromstring(out[i:j + len("</hierarchy>")]).iter("node"):
                label = ((n.get("text") or "").strip() or (n.get("content-desc") or "").strip()).replace("\n", " | ")
                m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds") or "")
                if label and m:
                    l, t, r, b = map(int, m.groups())
                    found.append((label, (l + r) // 2, (t + b) // 2, n.get("clickable") == "true"))
            return found
        time.sleep(0.6)
    raise SystemExit("could not read the screen")


def tap_label(sub, clickable_only=False):
    for label, x, y, click in screen():
        if sub.lower() in label.lower() and (click or not clickable_only):
            adb("shell", "input", "tap", str(x), str(y))
            return label
    return None


def wait_for(sub, seconds=20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        for label, x, y, click in screen():
            if sub.lower() in label.lower():
                return (label, x, y)
        time.sleep(0.5)
    return None


def player_state():
    """(state name, position ms, title) from the media session, plus whether an AudioTrack is started."""
    session = adb("shell", "dumpsys", "media_session")
    m = re.search(r"state=PlaybackState \{state=(\w+)\(\d+\), position=(\d+)", session)
    title = re.search(r"description=([^,\n]{0,60})", session)
    audio = adb("shell", "dumpsys", "audio").count("AudioTrack") and "state:started" in adb("shell", "dumpsys", "audio")
    return (m.group(1) if m else "NONE", int(m.group(2)) if m else -1, title.group(1) if title else "", bool(audio))


def _plain(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def find_row(artist, title):
    """A song row reads "Title | Artist - Album"; an album row reads "Album | Artist - 12 songs" and is never the one to tap.
    An exact title (ignoring punctuation) wins over one that only starts with it."""
    best = None
    for label, x, y, click in screen():
        parts = label.split(" | ")
        if not (click and len(parts) >= 2 and artist.lower() in parts[1].lower()):
            continue
        if re.search(r" - \d+ songs?$", parts[1]):
            continue
        first = _plain(parts[0])
        if first == _plain(title):
            return label, x, y
        if first.startswith(_plain(title)) and best is None:
            best = (label, x, y)
    return best


def measure(artist, title, limit=90.0):
    adb("shell", "input", "keyevent", "KEYCODE_MEDIA_PAUSE")
    if not tap_label("Search | Tab"):
        raise SystemExit("the Search tab is not on screen: open the app's main screen first")
    time.sleep(0.8)
    box = next(((x, y) for label, x, y, click in screen() if click and y < 400 and "Search" not in label), None)
    # The search box is the first clickable element under the title (its label is the typed text or empty).
    tap_label("Clear", clickable_only=True)  # the app's own button empties the box
    time.sleep(0.4)
    adb("shell", "input", "tap", "360", "277")
    adb("shell", "input", "text", f"{artist} {title}".replace(" ", "%s"))
    adb("shell", "input", "keyevent", "KEYCODE_BACK")  # hide the keyboard
    if wait_for(title.split()[0], 25) is None:
        return None, "no result row for the title"
    row = None
    for _ in range(4):  # the song may be below the first screenful
        row = find_row(artist, title)
        if row is not None:
            break
        adb("shell", "input", "swipe", "360", "1300", "360", "500", "300")
        time.sleep(0.8)
    if row is None:
        return None, f"no result row for {title!r} by {artist!r}"
    label, x, y = row
    t0 = time.monotonic()
    adb("shell", "input", "tap", str(x), str(y))
    last = None
    while time.monotonic() - t0 < limit:
        state, pos, desc, started = player_state()
        last = (state, pos, desc, started)
        if state == "PLAYING" and started and title.lower().split()[0] in desc.lower():
            return round(time.monotonic() - t0, 1), label
        time.sleep(0.25)
    return None, f"not audible within {limit:.0f} s (last: {last})"


def main():
    songs = [s.split("|", 1) for s in sys.argv[1:]]
    if not songs:
        print(__doc__)
        return 1
    results = []
    for artist, title in songs:
        seconds, note = measure(artist.strip(), title.strip())
        print(f"{artist.strip()} - {title.strip():30} {'%.1f s' % seconds if seconds is not None else 'FAILED'}   {note[:70]}")
        if seconds is not None:
            results.append(seconds)
        time.sleep(3)
    if results:
        ordered = sorted(results)
        p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
        print(f"n={len(results)}  median {statistics.median(results):.1f} s  p95 {p95:.1f} s  slowest {max(results):.1f} s  "
              f"(device {SERIAL}; a song new to the server each time)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
