#!/usr/bin/env python3
"""Measure what a person feels: frames while they scroll, memory, cold start.

    python -I perf_session.py LABEL [scenario ...]        (default: all)

Scenarios (docs/36 section 4 has the budgets they are held against):

  cold-start       force-stop, launch, `am start -W` total time, then 5 s of frames
  scroll-home      Home tab, 12 flings up and down
  scroll-library   Library tab, 12 flings up and down
  play-and-scroll  play the first song of the Library, then scroll while it plays;
                   counts audio underruns in the log (none allowed)

It reads the app's own `[perf] frames ...` lines (written to the log every 5 s while
frames are drawn), the process's memory (`dumpsys meminfo`) and its CPU
(`/proc/<pid>/stat`). Nothing in it is a secret; the phone must be signed in already.
The device is `emulator-5556` (ANDROID_SERIAL overrides). Results go to
docs/resource-samples/perf-LABEL--SCENARIO.json and a markdown row is printed.

The emulator is a stand-in: with `-gpu host` it draws like a good phone; with
`-gpu swiftshader_indirect` (software) it is the worst case. Say which one in LABEL.
"""
import json
import os
import re
import subprocess
import sys
import time

ADB = r"C:\dev\android-sdk\platform-tools\adb.exe"
SERIAL = os.environ.get("ANDROID_SERIAL", "emulator-5556")
PKG = "app.encore.player"
ACTIVITY = "app.encore.player/app.encore.player.MainActivity"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "docs", "resource-samples")


def adb(*a):
    r = subprocess.run([ADB, "-s", SERIAL, *a], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout.replace("\r", "")


def ui(*a):
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "ui.py"), *a],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout.strip()


def pid():
    out = adb("shell", "pidof", PKG).strip()
    return int(out.split()[0]) if out else None


def cpu_ticks(p):
    stat = adb("shell", f"cat /proc/{p}/stat")
    f = stat[stat.rfind(")") + 1:].split()
    return int(f[11]) + int(f[12])


def uptime():
    return float(adb("shell", "cat /proc/uptime").split()[0])


def memory():
    out = adb("shell", "dumpsys", "meminfo", PKG)
    m = re.search(r"TOTAL PSS:\s+(\d+)\s+TOTAL RSS:\s+(\d+)", out)
    if m:
        return {"pss_mb": round(int(m.group(1)) / 1024), "rss_mb": round(int(m.group(2)) / 1024)}
    m = re.search(r"TOTAL\s+(\d+)\s+\d+\s+\d+\s+\d+\s+(\d+)", out)
    return {"pss_mb": round(int(m.group(1)) / 1024), "rss_mb": None} if m else {}


FRAMES = re.compile(
    r"\[perf\] frames n=(\d+) jank=(\d+) \(([\d.]+)%\) severe=(\d+) "
    r"work p50=([\d.]+)ms p90=([\d.]+)ms p99=([\d.]+)ms late p90=([\d.]+)ms "
    r"worst\(build=([\d.]+) raster=([\d.]+)\)")


def frame_lines():
    out = adb("logcat", "-d", "-s", "flutter:I")
    rows = []
    for line in out.splitlines():
        m = FRAMES.search(line)
        if m:
            n, jank, pct, severe, p50, p90, p99, late, wb, wr = m.groups()
            rows.append({"n": int(n), "jank": int(jank), "severe": int(severe),
                         "p50": float(p50), "p90": float(p90), "p99": float(p99),
                         "late": float(late),
                         "worst_build": float(wb), "worst_raster": float(wr)})
    return rows


def underruns():
    """Times the audio server ran out of music to play (its own counters, summed over its output threads).
    Only meaningful with the emulator's audio ON; with -no-audio nothing is played and the count stays 0."""
    out = adb("shell", "dumpsys", "media.audio_flinger")
    return sum(int(a) + int(b) for a, b in re.findall(r"raw underrun counters: partial=(\d+) empty=(\d+)", out))


def fling(n=12):
    # 720x1600 screen; a fling is a fast swipe, like a thumb.
    for i in range(n):
        if i % 2 == 0:
            adb("shell", "input", "swipe", "360", "1250", "360", "350", "180")
        else:
            adb("shell", "input", "swipe", "360", "400", "360", "1250", "180")
        time.sleep(1.1)


def window(name, action, settle=6):
    """Run [action] and return what the frames, memory and CPU looked like."""
    adb("logcat", "-c")
    p = pid()
    t0, c0 = uptime(), cpu_ticks(p) if p else 0
    extra = action() or {}
    time.sleep(settle)  # the app writes a line every 5 s: let the last one out
    p = pid()
    elapsed = uptime() - t0
    cpu = (cpu_ticks(p) - c0) / 100 / elapsed * 100 if p else None
    rows = frame_lines()
    n = sum(r["n"] for r in rows)
    jank = sum(r["jank"] for r in rows)
    res = {
        "scenario": name,
        "frames": n,
        "jank": jank,
        "jank_pct": round(100 * jank / n, 1) if n else None,
        "severe": sum(r["severe"] for r in rows),
        "work_p50_ms": max((r["p50"] for r in rows), default=None),
        "work_p90_ms": max((r["p90"] for r in rows), default=None),
        "work_p99_ms": max((r["p99"] for r in rows), default=None),
        "late_p90_ms": max((r["late"] for r in rows), default=None),
        "worst_build_ms": max((r["worst_build"] for r in rows), default=None),
        "worst_raster_ms": max((r["worst_raster"] for r in rows), default=None),
        "cpu_pct_of_one_core": round(cpu) if cpu is not None else None,
        **memory(),
        **extra,
    }
    return res


def go(tab):
    code, out = ui("tap", tab)
    time.sleep(1.5)
    return code == 0


def scenario_cold_start():
    adb("shell", "am", "force-stop", PKG)
    time.sleep(2)

    def act():
        out = adb("shell", "am", "start", "-W", "-n", ACTIVITY)
        total = re.search(r"TotalTime:\s*(\d+)", out)
        wait = re.search(r"WaitTime:\s*(\d+)", out)
        time.sleep(4)
        return {"am_start_total_ms": int(total.group(1)) if total else None,
                "am_start_wait_ms": int(wait.group(1)) if wait else None}
    return window("cold-start", act, settle=3)


def scenario_scroll(tab, name):
    go(tab)
    return window(name, lambda: fling())


def playback_state():
    """PLAYING / PAUSED / ... of the app's own media session (`dumpsys media_session`)."""
    out = adb("shell", "dumpsys", "media_session")
    for m in re.finditer(r"package=app\.encore\.player", out):
        found = re.search(r"state=PlaybackState \{state=(\w+)", out[m.end():m.end() + 1500])
        if found:
            return found.group(1)
    return "unknown"


def scenario_play_and_scroll():
    """Music plays from the queue while the person flings the library: no glitch."""
    go("Your Library")
    # The media-play key toggles when it is already playing, so only press it when it is not.
    if playback_state() != "PLAYING":
        adb("shell", "input", "keyevent", "KEYCODE_MEDIA_PLAY")
        time.sleep(5)
    state = playback_state()
    if state not in ("PLAYING", "3", "BUFFERING"):
        print(f"  (not playing, state={state}: the numbers below are NOT a playing session)")

    before = underruns()

    def act():
        fling(12)
        return {"playback_state": playback_state()}
    res = window("play-and-scroll", act)
    res["audio_underruns_during"] = underruns() - before
    if playback_state() == "PLAYING":
        adb("shell", "input", "keyevent", "KEYCODE_MEDIA_PAUSE")
    return res


SCENARIOS = {
    "cold-start": scenario_cold_start,
    "scroll-home": lambda: scenario_scroll("Home", "scroll-home"),
    "scroll-library": lambda: scenario_scroll("Your Library", "scroll-library"),
    "play-and-scroll": scenario_play_and_scroll,
}


def main():
    label = sys.argv[1]
    wanted = sys.argv[2:] or list(SCENARIOS)
    os.makedirs(OUT, exist_ok=True)
    print("| scenario | frames | work > 16.7 ms | work p50 / p90 / p99 ms | late start p90 | worst build / raster | CPU of one core | PSS / RSS MB |")
    print("|---|---|---|---|---|---|---|---|")
    for name in wanted:
        r = SCENARIOS[name]()
        r["label"] = label
        with open(os.path.join(OUT, f"perf-{label}--{name}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2)
        print(f"| {name} | {r['frames']} | {r['jank']} ({r['jank_pct']} %) | "
              f"{r['work_p50_ms']} / {r['work_p90_ms']} / {r['work_p99_ms']} | {r['late_p90_ms']} | "
              f"{r['worst_build_ms']} / {r['worst_raster_ms']} | {r['cpu_pct_of_one_core']} % | "
              f"{r.get('pss_mb')} / {r.get('rss_mb')} |")
        sys.stdout.flush()


main()
