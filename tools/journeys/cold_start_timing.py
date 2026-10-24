#!/usr/bin/env python3
"""N1 from a cold start (docs/07 section 3; docs/evidence/b03): stop the app, start it, open Liked Songs as soon as Home is drawn, tap a song that
streams from the server, and time the seconds from the tap to sound. The first race for an address (and, since P2-19, the identity check) happens
while the person navigates, so a cost that hides in a warm app shows here.

    python -I cold_start_timing.py RUNS            (the songs rotate through Liked Songs; run the same RUNS on each build)

Device: emulator-5556 (ANDROID_SERIAL overrides). Be signed in, with the server up and its address in the list. "Audible" is the definition of
play_timing.py (media session PLAYING for this song AND a started AudioTrack). Prints one line per run, then the median, the slowest and the spread.
"""
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import play_timing as pt  # noqa: E402

PACKAGE = "app.encore.player"
SONGS = [("Breathe", "Breathe"), ("Reckoner", "Reckoner"), ("QUE CE SOIT", "QUE CE SOIT"), ("Nude", "Nude"), ("Weird Fishes", "Weird Fishes")]


def one_run(song):
    pt.adb("shell", "am", "force-stop", PACKAGE)
    time.sleep(1.5)
    launched = time.monotonic()
    pt.adb("shell", "monkey", "-p", PACKAGE, "-c", "android.intent.category.LAUNCHER", "1")
    home = pt.wait_for("Liked Songs", 30)
    if not home:
        return None
    seen_home = time.monotonic() - launched
    pt.adb("shell", "input", "tap", str(home[1]), str(home[2]))
    row = pt.wait_for(song[0], 15)
    if not row:
        return None
    t0 = time.monotonic()
    pt.adb("shell", "input", "tap", str(row[1]), str(row[2]))
    while time.monotonic() - t0 < 40:
        state, _position, title, audible = pt.player_state()
        if state == "PLAYING" and audible and song[1].lower() in title.lower():
            return seen_home, time.monotonic() - t0
    return seen_home, float("inf")


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    times = []
    for i in range(runs):
        song = SONGS[i % len(SONGS)]
        result = one_run(song)
        if result is None:
            print(f"run {i + 1}: {song[0]}: the screen never showed what was needed")
            continue
        home, took = result
        print(f"run {i + 1}: {song[0]:14s} home drawn {home:5.1f} s after launch, tap to sound {took:5.2f} s", flush=True)
        times.append(took)
    finite = [t for t in times if t != float("inf")]
    if finite:
        print(f"tap to sound over {len(finite)} cold starts: median {statistics.median(finite):.2f} s, slowest {max(finite):.2f} s, fastest {min(finite):.2f} s")
    if len(finite) != len(times):
        print(f"{len(times) - len(finite)} run(s) never became audible within 40 s")


if __name__ == "__main__":
    main()
