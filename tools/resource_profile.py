#!/usr/bin/env python3
"""Resource profile of the installed Encore build (RAM, CPU, GPU, battery proxies).

Samples the app process once a second from /proc while a scenario runs, then
reads the OS's own accounting at the end of the window:

  RAM      VmRSS per second (peak), PSS breakdown from `dumpsys meminfo`
  CPU      utime+stime of the app per second (percent of ONE core; 100 = one
           core busy), plus every other process that burned CPU in the window
           (surfaceflinger = compositing, audioserver/media.* = audio and
           decoding, system_server = framework work done on our behalf)
  GPU      Flutter's own frame statistics (the app logs a `[perf]` line every
           5 s while it draws: build/raster time, jank) plus `dumpsys gfxinfo`
           for GPU/HWUI memory (gfxinfo cannot see Flutter's surface)
  Battery  `dumpsys batterystats`: CPU time, wake locks, network, jobs. The
           emulator has no real discharge and its power profile has CPU = 0 mA,
           so only these *proxies* are meaningful there; real mAh needs a
           phone (docs/15-resource-usage.md).

Usage (an emulator or phone on adb, build installed, app logged in):

  python tool/resource_profile.py --label "0.1.0-rc2 release x64" --scenario idle-home
  python tool/resource_profile.py --label "..." --all          # every scenario
  python tool/resource_profile.py --label "..." --scenario custom --seconds 60
        (samples only; drive the app by hand while it runs)

Writes docs/resource-samples/<label>--<scenario>.json and prints a markdown row.
Coordinates assume the 1080x2400 emulator layout; labels are found through
uiautomator where possible. Playback scenarios turn *Private listening* on
first (and refuse to run if that cannot be confirmed) so a measurement never
scrobbles to a shared server.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time

PKG = 'app.encore.player'
ACTIVITY = f'{PKG}/app.encore.player.MainActivity'
CLK_TCK = 100  # Linux USER_HZ on Android

# Device pixels on the 1080x2400 emulator.
NAV = {'home': (180, 2280), 'search': (540, 2280), 'library': (900, 2280)}
MINI_PLAY = (998, 2076)


# ------------------------------------------------------------------ adb ----
def find_adb() -> str:
    exe = shutil.which('adb')
    if exe:
        return exe
    for root in (os.environ.get('ANDROID_HOME'), os.environ.get('ANDROID_SDK_ROOT'),
                 r'C:\dev\android-sdk'):
        if root:
            cand = os.path.join(root, 'platform-tools', 'adb.exe' if os.name == 'nt' else 'adb')
            if os.path.exists(cand):
                return cand
    sys.exit('adb not found (put platform-tools on PATH or set ANDROID_HOME)')


ADB = find_adb()
SERIAL: list[str] = []


def adb(*args: str, timeout: int = 120) -> str:
    env = dict(os.environ, MSYS_NO_PATHCONV='1')
    out = subprocess.run([ADB, *SERIAL, *args], capture_output=True, text=True,
                         timeout=timeout, env=env)
    return out.stdout.replace('\r', '')


def sh(cmd: str, timeout: int = 120) -> str:
    return adb('shell', cmd, timeout=timeout)


def tap(x: int, y: int) -> None:
    sh(f'input tap {x} {y}')


def swipe(x1: int, y1: int, x2: int, y2: int, ms: int = 350) -> None:
    sh(f'input swipe {x1} {y1} {x2} {y2} {ms}')


def pid() -> int | None:
    out = sh(f'pidof -s {PKG}').strip()
    return int(out) if out.isdigit() else None


# ------------------------------------------------------------ UI helpers ---
NODE_RE = re.compile(r'<node [^>]*>')
DESC_RE = re.compile(r'''content-desc=(?:"([^"]*)"|'([^']*)')''')
BOX_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
CHECKED_RE = re.compile(r'checked="(true|false)"')


def ui_nodes() -> list[dict]:
    """Every labelled node on screen: {desc, x, y, checked}."""
    sh('uiautomator dump /sdcard/encore_ui.xml')
    xml = sh('cat /sdcard/encore_ui.xml')
    nodes = []
    for m in NODE_RE.finditer(xml):
        tag = m.group(0)
        desc = DESC_RE.search(tag)
        box = BOX_RE.search(tag)
        label = (desc.group(1) or desc.group(2)) if desc else ''
        if not label or not box:
            continue
        x1, y1, x2, y2 = (int(v) for v in box.groups())
        checked = CHECKED_RE.search(tag)
        nodes.append({
            'desc': ' / '.join(html.unescape(label).splitlines()),
            'x': (x1 + x2) // 2,
            'y': (y1 + y2) // 2,
            'checked': None if not checked else checked.group(1) == 'true',
        })
    return nodes


def find_node(pattern: str, attempts: int = 4) -> dict | None:
    rx = re.compile(pattern, re.I | re.S)
    for _ in range(attempts):
        for node in ui_nodes():
            if rx.search(node['desc']):
                return node
        time.sleep(0.7)
    return None


def tap_desc(pattern: str, attempts: int = 4) -> bool:
    """Taps the first node whose label matches [pattern]; False if none."""
    node = find_node(pattern, attempts)
    if node:
        tap(node['x'], node['y'])
    return node is not None


def back() -> None:
    sh('input keyevent KEYCODE_BACK')
    time.sleep(0.6)


def set_private_listening(enabled: bool) -> bool:
    """Settings > Home, library & privacy > Private listening (idempotent).

    Returns whether the switch ended in the requested state.
    """
    ok = False
    if tap_desc(r'^Settings$'):
        time.sleep(1)
        if tap_desc(r'Home, library & privacy'):
            time.sleep(1)
            node = find_node(r'^Private listening')
            if node is not None:
                if node['checked'] is not enabled:
                    tap(node['x'], node['y'])
                    time.sleep(0.8)
                    node = find_node(r'^Private listening')
                ok = node is not None and node['checked'] is enabled
    back()
    back()
    return ok


# -------------------------------------------------------------- sampling ---
def snapshot_processes() -> dict[int, tuple[str, int]]:
    """pid -> (name, utime+stime ticks) for every process."""
    out = sh("for f in /proc/[0-9]*/stat; do cat $f 2>/dev/null; done", timeout=60)
    procs: dict[int, tuple[str, int]] = {}
    for line in out.splitlines():
        m = re.match(r'(\d+) \((.*)\) \S (.*)', line)
        if not m:
            continue
        rest = m.group(3).split()
        if len(rest) < 13:
            continue
        procs[int(m.group(1))] = (m.group(2), int(rest[10]) + int(rest[11]))
    return procs


def start_sampler(app_pid: int, seconds: int) -> subprocess.Popen:
    script = (
        f'n=0; while [ $n -lt {seconds} ]; do '
        f'read up idle < /proc/uptime; echo "T $up"; '
        f'cat /proc/{app_pid}/stat 2>/dev/null; '
        f'grep -E "^(VmRSS|Threads)" /proc/{app_pid}/status 2>/dev/null; '
        f'n=$((n+1)); sleep 1; done; echo END'
    )
    env = dict(os.environ, MSYS_NO_PATHCONV='1')
    return subprocess.Popen([ADB, *SERIAL, 'shell', script], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)


def parse_samples(raw: str) -> list[dict]:
    samples: list[dict] = []
    cur: dict = {}
    for line in raw.replace('\r', '').splitlines():
        if line.startswith('T '):
            if cur.get('t') is not None and 'ticks' in cur:
                samples.append(cur)
            cur = {'t': float(line.split()[1])}
        elif re.match(r'^\d+ \(', line):
            m = re.match(r'\d+ \((.*)\) \S (.*)', line)
            rest = m.group(2).split()
            cur['ticks'] = int(rest[10]) + int(rest[11])
        elif line.startswith('VmRSS'):
            cur['rss_kb'] = int(line.split()[1])
        elif line.startswith('Threads'):
            cur['threads'] = int(line.split()[1])
    if cur.get('t') is not None and 'ticks' in cur:
        samples.append(cur)
    return samples


def cpu_series(samples: list[dict]) -> list[tuple[float, float]]:
    """(seconds since start, percent of one core) per interval."""
    series = []
    for a, b in zip(samples, samples[1:]):
        dt = b['t'] - a['t']
        if dt <= 0:
            continue
        series.append((b['t'] - samples[0]['t'],
                       100.0 * (b['ticks'] - a['ticks']) / CLK_TCK / dt))
    return series


# -------------------------------------------------------- OS accounting ----
def meminfo() -> dict:
    out = sh(f'dumpsys meminfo {PKG}')
    res: dict = {}
    m = re.search(r'TOTAL PSS:\s+(\d+)\s+TOTAL RSS:\s+(\d+)', out)
    if m:
        res['pss_total_kb'], res['rss_total_kb'] = int(m.group(1)), int(m.group(2))
    for key, label in (('java_kb', 'Java Heap'), ('native_kb', 'Native Heap'),
                       ('code_kb', 'Code'), ('stack_kb', 'Stack'),
                       ('graphics_kb', 'Graphics'), ('private_other_kb', 'Private Other'),
                       ('system_kb', 'System')):
        m = re.search(rf'^\s*{label}:\s+(\d+)', out, re.M)
        if m:
            res[key] = int(m.group(1))
    m = re.search(r'Views:\s+(\d+)', out)
    if m:
        res['views'] = int(m.group(1))
    return res


def gfxinfo() -> dict:
    out = sh(f'dumpsys gfxinfo {PKG}')
    res: dict = {}

    def num(pattern: str, key: str, cast=float):
        m = re.search(pattern, out, re.M)
        if m:
            res[key] = cast(m.group(1))

    num(r'Total frames rendered:\s+(\d+)', 'frames', int)
    num(r'Janky frames:\s+\d+ \(([\d.]+)%\)', 'janky_pct')
    num(r'^50th percentile:\s+(\d+)ms', 'frame_p50_ms', int)
    num(r'^90th percentile:\s+(\d+)ms', 'frame_p90_ms', int)
    num(r'^95th percentile:\s+(\d+)ms', 'frame_p95_ms', int)
    num(r'^99th percentile:\s+(\d+)ms', 'frame_p99_ms', int)
    num(r'^50th gpu percentile:\s+(\d+)ms', 'gpu_p50_ms', int)
    num(r'^90th gpu percentile:\s+(\d+)ms', 'gpu_p90_ms', int)
    num(r'^99th gpu percentile:\s+(\d+)ms', 'gpu_p99_ms', int)
    num(r'Number Slow UI thread:\s+(\d+)', 'slow_ui', int)
    num(r'Number Slow bitmap uploads:\s+(\d+)', 'slow_bitmap', int)
    num(r'Number Slow issue draw commands:\s+(\d+)', 'slow_draw', int)
    m = re.search(r'Total GPU memory usage:\s*\n\s*(\d+) bytes', out)
    if m:
        res['gpu_mem_kb'] = int(m.group(1)) // 1024
    m = re.search(r'Total CPU memory usage:\s*\n\s*(\d+) bytes', out)
    if m:
        res['hwui_cpu_cache_kb'] = int(m.group(1)) // 1024
    return res


def _dur_s(text: str) -> float:
    """'1h 2m 3s 400ms' -> seconds."""
    total = 0.0
    for value, unit in re.findall(r'(\d+)(ms|s|m|h|d)\b', text):
        total += int(value) * {'ms': 0.001, 's': 1, 'm': 60, 'h': 3600, 'd': 86400}[unit]
    return total


def batterystats() -> dict:
    out = sh(f'dumpsys batterystats --charged {PKG}', timeout=180)
    res: dict = {}
    uid = None
    m = re.search(r'^\s+(u0a\d+):\s*$', out, re.M)
    if m:
        uid = m.group(1)
        block = out[m.end():]
        block = block.split('\n  u0a', 1)[0].split('\n  UID', 1)[0]
        m2 = re.search(r'Total cpu time: u=(.*?) s=(.*)', block)
        if m2:
            res['cpu_user_s'] = _dur_s(m2.group(1))
            res['cpu_kernel_s'] = _dur_s(m2.group(2))
        m2 = re.search(
            r'Wi-Fi network: ([\d.]+)(KB|MB|GB|B) received, ([\d.]+)(KB|MB|GB|B) sent', block)
        if m2:
            mult = {'B': 1, 'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3}
            res['wifi_rx_kb'] = round(float(m2.group(1)) * mult[m2.group(2)] / 1024, 1)
            res['wifi_tx_kb'] = round(float(m2.group(3)) * mult[m2.group(4)] / 1024, 1)
        m2 = re.search(r'TOTAL wake: (.*?) (?:full|partial)', block)
        res['wakelock_s'] = _dur_s(m2.group(1)) if m2 else 0.0
        m2 = re.search(r'Foreground activities: (.*?) realtime', block)
        res['foreground_s'] = _dur_s(m2.group(1)) if m2 else 0.0
        m2 = re.search(r'Foreground services: (.*?) realtime', block)
        res['fg_service_s'] = _dur_s(m2.group(1)) if m2 else 0.0
        jobs = re.findall(r'Job @androidx\.work[^:]*: (.*?) realtime \((\d+) times\)', block)
        res['job_runs'] = sum(int(n) for _, n in jobs)
    if uid:
        m = re.search(rf'UID {uid}: ([\d.]+)', out)
        if m:
            res['os_estimate_mah'] = float(m.group(1))
    return res


PERF_RE = re.compile(
    r'\[perf\] frames n=(\d+) jank=(\d+) \([\d.]+%\) severe=(\d+) '
    r'p50=([\d.]+)ms p90=([\d.]+)ms p99=([\d.]+)ms '
    r'worst\(build=([\d.]+) raster=([\d.]+)\)')


def flutter_frames() -> dict:
    """Flutter's own frame statistics for the window.

    `dumpsys gfxinfo` only sees the Android view hierarchy; Flutter draws on
    its own surface, so the app's `PerfMonitor` (a `[perf]` line every 5 s while
    frames are produced) is the source of truth for build/raster times.
    """
    out = sh('logcat -d -s flutter:I')
    n = jank = severe = 0
    p50s: list[float] = []
    p90s: list[float] = []
    worst_build = worst_raster = p99_max = 0.0
    windows = 0
    for m in PERF_RE.finditer(out):
        windows += 1
        n += int(m.group(1))
        jank += int(m.group(2))
        severe += int(m.group(3))
        p50s.append(float(m.group(4)))
        p90s.append(float(m.group(5)))
        p99_max = max(p99_max, float(m.group(6)))
        worst_build = max(worst_build, float(m.group(7)))
        worst_raster = max(worst_raster, float(m.group(8)))
    if not windows:
        return {'frames': 0}
    return {
        'frames': n,
        'jank_pct': round(100 * jank / n, 1) if n else 0.0,
        'severe_pct': round(100 * severe / n, 1) if n else 0.0,
        'frame_p50_ms': round(statistics.median(p50s), 1),
        'frame_p90_ms': round(statistics.median(p90s), 1),
        'frame_p99_worst_ms': p99_max,
        'worst_build_ms': worst_build,
        'worst_raster_ms': worst_raster,
        'windows': windows,
    }


def reset_os_counters() -> None:
    sh(f'dumpsys gfxinfo {PKG} reset')
    sh('dumpsys batterystats --reset')
    sh('logcat -c')


def device_info() -> dict:
    ver = sh(f'dumpsys package {PKG}')
    return {
        'device': sh('getprop ro.product.model').strip(),
        'android_api': int(sh('getprop ro.build.version.sdk').strip() or 0),
        'abi': sh('getprop ro.product.cpu.abi').strip(),
        'cores': int(sh('nproc').strip() or 0),
        'versionName': (re.search(r'versionName=(\S+)', ver) or [None, ''])[1],
        'versionCode': (re.search(r'versionCode=(\d+)', ver) or [None, ''])[1],
        'emulator': 'sdk' in sh('getprop ro.product.model').lower()
        or sh('getprop ro.kernel.qemu').strip() == '1',
    }


# ------------------------------------------------------------ scenarios ----
def on_home() -> bool:
    """True when the bottom bar is visible with Home selected."""
    return any(n['desc'].startswith('Home') and 'Tab 1 of 3' in n['desc']
               for n in ui_nodes())


def wake_and_home() -> None:
    """Screen on, app in front, Home tab showing - without restarting it."""
    sh('input keyevent KEYCODE_WAKEUP')
    if not pid():
        sh(f'am start -n {ACTIVITY}')
        time.sleep(3)
    else:
        sh(f'am start -n {ACTIVITY}')  # bring to front (no-op when there)
        time.sleep(1.5)
    for _ in range(5):
        nodes = ui_nodes()
        if any('Tab 1 of 3' in n['desc'] for n in nodes):
            break  # the bottom bar is there: a normal screen
        back()  # a full-screen route (player, lyrics) or a sub-page
    tap(*NAV['home'])
    time.sleep(1)


def is_playing() -> bool:
    out = sh('dumpsys media_session')
    return bool(re.search(r'state=PlaybackState \{state=PLAYING\(3\)', out))


def start_playback() -> bool:
    """Restarts the current song from its start and makes sure it plays.

    Media keys instead of the toggle button, so a scenario never *pauses*
    what an earlier one left playing, and a song that had reached its end is
    replayed from 0:00.
    """
    sh('input keyevent KEYCODE_MEDIA_PREVIOUS')
    time.sleep(1)
    for attempt in range(4):
        sh('input keyevent KEYCODE_MEDIA_PLAY')
        time.sleep(2.5)
        if is_playing():
            return True
        if attempt == 1:
            tap(*MINI_PLAY)  # the media session was not active: use the UI
            time.sleep(2.5)
            if is_playing():
                return True
    return False


def scroll_run(n: int = 12) -> None:
    for i in range(n):
        if i % 2 == 0:
            swipe(540, 1700, 540, 700, 350)
        else:
            swipe(540, 700, 540, 1700, 350)
        time.sleep(0.8)


SCENARIOS: dict[str, dict] = {
    'cold-start': {
        'seconds': 25,
        'doc': 'process start to Home drawn from the local database, then settle '
               '(includes the app-start sync pass)',
    },
    'idle-home': {
        'seconds': 60,
        'doc': 'Home on screen, no input: the lowest steady cost with the screen on',
    },
    'idle-background': {
        'seconds': 60,
        'doc': 'app sent to the background, nothing playing: what it costs while '
               'the phone is in a pocket',
    },
    'scroll-home': {
        'seconds': 20,
        'doc': 'twelve flings up/down the Home shelves',
    },
    'scroll-library': {
        'seconds': 20,
        'doc': 'twelve flings through Your Library (artwork loads)',
    },
    'playback-screen-on': {
        'seconds': 45,
        'doc': 'a library song streaming, mini player visible (private listening on)',
        'private': True,
    },
    'lyrics': {
        'seconds': 30,
        'doc': 'full-screen lyrics open while the song plays (private listening on)',
        'private': True,
    },
    'playback-screen-off': {
        'seconds': 90,
        'doc': 'same song, screen off: the cost of listening with the phone in a '
               'pocket (private listening on)',
        'private': True,
    },
    'sync-now': {
        'seconds': 30,
        'doc': 'Settings > Library & sync > Sync now on an unchanged library',
    },
    'background-sync': {
        'seconds': 30,
        'doc': 'the WorkManager sync job run while the app is in the background',
    },
    'emulator-floor': {
        'seconds': 30,
        'doc': 'the app stopped: what the emulator itself burns (subtract from '
               '"other processes")',
    },
    'custom': {
        'seconds': 60,
        'doc': 'sampling only; drive the app by hand',
    },
}


def drive(name: str) -> None:
    """Performs the scenario's input while the sampler runs."""
    if name in ('cold-start', 'idle-home', 'custom'):
        return
    if name == 'idle-background':
        sh('input keyevent KEYCODE_HOME')
    elif name == 'scroll-home':
        scroll_run(12)
    elif name == 'scroll-library':
        tap(*NAV['library'])
        time.sleep(2)
        scroll_run(12)
    elif name == 'playback-screen-on':
        if not start_playback():
            print('WARNING: playback did not start', file=sys.stderr)
    elif name == 'lyrics':
        if not start_playback():
            print('WARNING: playback did not start', file=sys.stderr)
        if tap_desc(r'Open player'):  # the mini player's "Open player" action
            time.sleep(2)
            tap_desc(r'^Lyrics$')
    elif name == 'playback-screen-off':
        if not start_playback():
            print('WARNING: playback did not start', file=sys.stderr)
        time.sleep(2)
        sh('input keyevent KEYCODE_SLEEP')
    elif name == 'sync-now':
        if tap_desc(r'^Settings$'):
            time.sleep(1)
            if tap_desc(r'Library & sync'):
                time.sleep(1)
                tap_desc(r'Sync now')
    elif name == 'background-sync':
        sh('input keyevent KEYCODE_HOME')
        time.sleep(1)
        job_id = None
        for line in sh('dumpsys jobscheduler').splitlines():
            m = re.search(rf'JOB #u0a\d+/(\d+): .*{PKG}.*SystemJobService', line)
            if m:
                job_id = m.group(1)
                break
        if job_id:
            sh(f'cmd jobscheduler run -f -n androidx.work.systemjobscheduler {PKG} {job_id}')


def write_result(result: dict, label: str, name: str, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    slug = re.sub(r'[^A-Za-z0-9._-]+', '_', label)
    path = os.path.join(out_dir, f'{slug}--{name}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    return path


def run_floor(label: str, seconds: int, out_dir: str) -> dict:
    sh(f'am force-stop {PKG}')
    time.sleep(2)
    before = snapshot_processes()
    t0 = time.time()
    time.sleep(seconds)
    after = snapshot_processes()
    wall = time.time() - t0
    merged: dict[str, float] = {}
    for p, (pname, ticks) in after.items():
        delta = ticks - before.get(p, (pname, 0))[1]
        if delta > 0:
            merged[pname] = merged.get(pname, 0.0) + delta / CLK_TCK
    top = sorted(merged.items(), key=lambda kv: -kv[1])[:6]
    result = {
        'label': label,
        'scenario': 'emulator-floor',
        'what': SCENARIOS['emulator-floor']['doc'],
        'window_s': round(wall, 1),
        'device': device_info(),
        'floor_cpu_pct_of_core': {k: round(100 * v / wall, 1) for k, v in top},
    }
    write_result(result, label, 'emulator-floor', out_dir)
    print('| emulator-floor | %.0f s | - | - | - | - | %s |' % (
        wall, ', '.join(f'{k} {v}%' for k, v in result['floor_cpu_pct_of_core'].items())))
    return result


def run_scenario(name: str, label: str, seconds: int | None, out_dir: str) -> dict:
    spec = SCENARIOS[name]
    seconds = seconds or spec['seconds']
    if name == 'emulator-floor':
        return run_floor(label, seconds, out_dir)

    if not pid():
        sh(f'am start -n {ACTIVITY}')
        time.sleep(4)
    if spec.get('private'):
        wake_and_home()
        if not set_private_listening(True):
            raise SystemExit('could not confirm Private listening is ON; refusing to '
                             'play music against a shared server (use the build that '
                             'has the setting)')

    if name == 'cold-start':
        sh(f'am force-stop {PKG}')
        time.sleep(1)
        reset_os_counters()
        launch = sh(f'am start -W -n {ACTIVITY}')
        m = re.search(r'TotalTime:\s+(\d+)', launch)
        launch_ms = int(m.group(1)) if m else None
    else:
        wake_and_home()
        reset_os_counters()
        launch_ms = None

    app_pid = pid()
    if not app_pid:
        raise SystemExit('app is not running')
    before = snapshot_processes()
    t0 = time.time()
    sampler = start_sampler(app_pid, seconds)
    drive(name)
    raw, _ = sampler.communicate(timeout=seconds + 90)
    after = snapshot_processes()
    wall = time.time() - t0
    if name == 'playback-screen-off':
        sh('input keyevent KEYCODE_WAKEUP')
    if name in ('playback-screen-on', 'lyrics', 'playback-screen-off'):
        sh('input keyevent KEYCODE_MEDIA_PAUSE')

    samples = parse_samples(raw)
    series = cpu_series(samples)
    cpu_vals = [v for _, v in series] or [0.0]
    rss = [s['rss_kb'] for s in samples if 'rss_kb' in s] or [0]
    top = sorted(series, key=lambda p: -p[1])[:3]

    merged: dict[str, float] = {}
    for p, (pname, ticks) in after.items():
        delta = ticks - before.get(p, (pname, 0))[1]
        if delta > 0 and p != app_pid:
            merged[pname] = merged.get(pname, 0.0) + delta / CLK_TCK
    top_others = sorted(merged.items(), key=lambda kv: -kv[1])[:4]
    app_cpu_s = (after.get(app_pid, ('', 0))[1] - before.get(app_pid, ('', 0))[1]) / CLK_TCK

    # CPU the process had used when sampling began: for cold-start this is the
    # start-up itself (process start to first frame and the first sync pass).
    startup_cpu_s = round(samples[0]['ticks'] / CLK_TCK, 2) if samples else None
    result = {
        'label': label,
        'scenario': name,
        'what': spec['doc'],
        'window_s': round(wall, 1),
        'device': device_info(),
        'launch_ms': launch_ms,
        'cpu': {
            'cpu_seconds_before_window': startup_cpu_s,
            'app_cpu_seconds': round(app_cpu_s, 2),
            'avg_pct_of_core': round(statistics.fmean(cpu_vals), 1),
            'p95_pct_of_core': round(sorted(cpu_vals)[int(0.95 * (len(cpu_vals) - 1))], 1),
            'max_pct_of_core': round(max(cpu_vals), 1),
            'peak_at_s': [round(t, 1) for t, _ in top],
            'series_pct': [round(v, 1) for _, v in series],
            'other_processes_cpu_s': {k: round(v, 2) for k, v in top_others},
        },
        'ram': {
            'rss_start_mb': round(rss[0] / 1024, 1),
            'rss_max_mb': round(max(rss) / 1024, 1),
            'rss_end_mb': round(rss[-1] / 1024, 1),
            'threads_end': samples[-1].get('threads') if samples else None,
            **meminfo(),
        },
        'gpu': {**gfxinfo(), 'flutter': flutter_frames()},
        'battery_proxies': batterystats(),
    }
    write_result(result, label, name, out_dir)
    print(markdown_row(result))
    return result


def markdown_row(r: dict) -> str:
    c, m, g, b = r['cpu'], r['ram'], r['gpu'], r['battery_proxies']
    f = g.get('flutter', {})
    others = ', '.join(f"{k} {v}s" for k, v in c['other_processes_cpu_s'].items()) or '-'
    if f.get('frames'):
        frames = (f"{f['frames']} frames, {f['jank_pct']}% over 16.7 ms, "
                  f"p50 {f['frame_p50_ms']} / p90 {f['frame_p90_ms']} ms, "
                  f"worst build {f['worst_build_ms']} / raster {f['worst_raster_ms']} ms")
    else:
        frames = 'no frames drawn'
    return (
        f"| {r['scenario']} | {r['window_s']:.0f} s | "
        f"{c['avg_pct_of_core']}% / {c['p95_pct_of_core']}% / {c['max_pct_of_core']}% "
        f"({c['app_cpu_seconds']} cpu-s) | "
        f"{m.get('pss_total_kb', 0) / 1024:.0f} MB PSS, {m['rss_max_mb']} MB RSS peak | "
        f"{frames}; GPU memory {g.get('gpu_mem_kb', 0)} KB | "
        f"{b.get('wakelock_s', 0):.0f} s wake, "
        f"{b.get('wifi_rx_kb', 0):.0f} KB rx | {others} |"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--label', required=True, help='build label, e.g. "0.1.0-rc2 release x64"')
    ap.add_argument('--scenario', choices=sorted(SCENARIOS))
    ap.add_argument('--all', action='store_true', help='run every scenario in turn')
    ap.add_argument('--skip-playback', action='store_true',
                    help='with --all: leave out scenarios that play music')
    ap.add_argument('--seconds', type=int, help='override the sampling window')
    ap.add_argument('--serial', help='adb device serial')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(__file__), '..', 'docs',
                                                  'resource-samples'))
    args = ap.parse_args()
    if args.serial:
        SERIAL[:] = ['-s', args.serial]
    if args.all:
        names = [n for n in SCENARIOS if n != 'custom']
        if args.skip_playback:
            names = [n for n in names if not SCENARIOS[n].get('private')]
    else:
        names = [args.scenario or 'idle-home']
    print('| scenario | window | app CPU avg / p95 / max (% of one core) | RAM | GPU / frames | '
          'battery proxies | other processes (CPU) |')
    print('|---|---|---|---|---|---|---|')
    for n in names:
        run_scenario(n, args.label, args.seconds, os.path.normpath(args.out))
        time.sleep(2)


if __name__ == '__main__':
    main()
