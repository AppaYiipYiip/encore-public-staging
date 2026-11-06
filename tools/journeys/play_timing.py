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


_SCALE = None


def at(x, y):
    """A point measured on a 720x1600 screen, moved to this device's screen: the tool used to tap fixed pixels, which hit the wrong place on a 1080x2400 emulator or a
    1080x2340 phone (found 6 Nov 2026, P1-06)."""
    global _SCALE
    if _SCALE is None:
        size = re.search(r"(\d+)x(\d+)", adb("shell", "wm", "size"))
        w, h = (int(size.group(1)), int(size.group(2))) if size else (720, 1600)
        _SCALE = (w / 720, h / 1600)
    return str(round(x * _SCALE[0])), str(round(y * _SCALE[1]))


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


def _core(text):
    """A title without its bracketed tail: the catalogue lists "Instant Crush (feat. Julian Casablancas)" and "Windowpane (Remastered 2015)" for what a person types as
    "Instant Crush" and "Windowpane" (found 6 Nov 2026: the strict match made a real song "not found")."""
    return _plain(re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", text))


def _plain(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def find_row(artist, title):
    """A song row reads "Title | Artist - Album" (or "Artist • Album"); an album row reads "Album | Artist - 12 songs" and is never the one
    to tap, and the Top result card reads "Top result: Song, Title, Artist". The artist must be the song's own (not a tribute whose album
    names it); the title must match exactly (ignoring punctuation and a trailing edition mark), or else there is no row."""
    for label, x, y, click in screen():
        if label.startswith("Top result: Song, "):
            _, _, rest = label.partition("Top result: Song, ")
            name, _, by = rest.rpartition(", ")
            if _core(name) == _core(title) and artist.lower() in by.lower():
                return label, x, y
    for label, x, y, click in screen():
        parts = label.split(" | ")
        if not (click and len(parts) >= 2):
            continue
        by = re.split(r" [-•] ", parts[1])[0]
        if artist.lower() not in by.lower() or re.search(r" - \d+ songs?$", parts[1]):
            continue
        if _core(parts[0]) == _core(title):
            return label, x, y
    return None


def app_span():
    """The app's own `[perf] span play.audible N ms` for the tap just made: THE number (docs/07 section 3). This tool's own polling (three adb calls a round) added
    about 0.6 s to what it printed before 6 Nov 2026 (the app said 2.55 s where this tool said 3.2 s)."""
    for _ in range(8):
        found = re.findall(r"span play\.audible (\d+) ms", adb("logcat", "-d", "-s", "flutter:I"))
        if found:
            return round(int(found[-1]) / 1000, 2)
        time.sleep(0.4)
    return None


def measure(artist, title, limit=90.0):
    adb("shell", "input", "keyevent", "KEYCODE_MEDIA_PAUSE")
    if not tap_label("Search | Tab"):
        raise SystemExit("the Search tab is not on screen: open the app's main screen first")
    time.sleep(0.8)
    top = int(at(0, 400)[1])
    box = next(((x, y) for label, x, y, click in screen() if click and y < top and "Search" not in label), None)
    # The search box is the first clickable element under the title (its label is the typed text or empty).
    tap_label("Clear", clickable_only=True)  # the app's own button empties the box
    time.sleep(0.4)
    adb("shell", "input", "tap", *(map(str, box) if box else at(360, 277)))   # the box the screen shows; the old fixed point only when none was found
    adb("shell", "input", "text", f"{artist} {title}".replace(" ", "%s"))
    adb("shell", "input", "keyevent", "KEYCODE_BACK")  # hide the keyboard
    if wait_for(title.split()[0], 25) is None:
        return None, "no result row for the title"
    row = None
    for _ in range(4):  # the song may be below the first screenful
        row = find_row(artist, title)
        if row is not None:
            break
        adb("shell", "input", "swipe", *at(360, 1300), *at(360, 500), "300")
        time.sleep(0.8)
    if row is None:
        return None, f"no result row for {title!r} by {artist!r}"
    label, x, y = row
    adb("logcat", "-c")                       # so the span read below is this tap's
    t0 = time.monotonic()
    adb("shell", "input", "tap", str(x), str(y))
    last = None
    while time.monotonic() - t0 < limit:
        state, pos, desc, started = player_state()
        last = (state, pos, desc, started)
        if state == "PLAYING" and started and title.lower().split()[0] in desc.lower():
            span = app_span()
            if span is not None:
                return span, label
            return round(time.monotonic() - t0, 2), label + "   [this tool's own polling: the app logged no span]"
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
        print(f"{artist.strip()} - {title.strip():30} {'%.2f s' % seconds if seconds is not None else 'FAILED'}   {note[:70]}")
        if seconds is not None:
            results.append(seconds)
        time.sleep(3)
    if results:
        ordered = sorted(results)
        p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
        print(f"n={len(results)}  median {statistics.median(results):.2f} s  p95 {p95:.2f} s  slowest {max(results):.2f} s  "
              f"(device {SERIAL}; a song new to the server each time)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
