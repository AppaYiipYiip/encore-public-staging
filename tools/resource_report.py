#!/usr/bin/env python3
"""Turns docs/resource-samples/*.json into the markdown tables of
docs/15-resource-usage.md.

  python tool/resource_report.py            # every build found
  python tool/resource_report.py "C "       # only labels starting with "C "
"""
from __future__ import annotations

import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.normpath(os.path.join(HERE, '..', 'docs', 'resource-samples'))

ORDER = ['cold-start', 'idle-home', 'idle-background', 'scroll-home',
         'scroll-library', 'sync-now', 'background-sync', 'playback-screen-on',
         'lyrics', 'playback-screen-off', 'emulator-floor']


def load(prefix: str | None) -> dict[str, dict[str, dict]]:
    builds: dict[str, dict[str, dict]] = {}
    for path in sorted(glob.glob(os.path.join(SAMPLES, '*.json'))):
        with open(path, encoding='utf-8') as f:
            r = json.load(f)
        label = r.get('label', '?')
        if prefix and not label.startswith(prefix):
            continue
        builds.setdefault(label, {})[r['scenario']] = r
    return builds


def sparkline(values: list[float], width: int = 40) -> str:
    if not values:
        return ''
    blocks = ' .:-=+*#%@'
    top = max(values) or 1.0
    step = max(1, len(values) // width)
    out = []
    for i in range(0, len(values), step):
        chunk = values[i:i + step]
        out.append(blocks[min(len(blocks) - 1, int(max(chunk) / top * (len(blocks) - 1)))])
    return ''.join(out)


def row(r: dict) -> str:
    if r['scenario'] == 'emulator-floor':
        floor = ', '.join(f'{k} {v}%' for k, v in r['floor_cpu_pct_of_core'].items())
        return f"| emulator-floor | {r['window_s']:.0f} s | - | - | - | {floor} |"
    c, m, g = r['cpu'], r['ram'], r['gpu']
    f = g.get('flutter', {})
    frames = (f"{f['frames']} frames, {f['jank_pct']}% > 16.7 ms, p50 "
              f"{f['frame_p50_ms']} / p90 {f['frame_p90_ms']} ms, worst build "
              f"{f['worst_build_ms']} / raster {f['worst_raster_ms']} ms"
              if f.get('frames') else 'no frames drawn')
    others = ', '.join(f'{k} {v}s' for k, v in c['other_processes_cpu_s'].items())
    startup = ''
    if r['scenario'] == 'cold-start' and c.get('cpu_seconds_before_window') is not None:
        startup = (f" + {c['cpu_seconds_before_window']} cpu-s to get to the first "
                   f"frame ({r.get('launch_ms')} ms)")
    return (f"| {r['scenario']} | {r['window_s']:.0f} s | "
            f"**{c['avg_pct_of_core']}%** / {c['p95_pct_of_core']}% / {c['max_pct_of_core']}% "
            f"({c['app_cpu_seconds']} cpu-s{startup}) | "
            f"{m.get('pss_total_kb', 0) / 1024:.0f} MB PSS, {m['rss_max_mb']} MB RSS peak | "
            f"{frames} | {others} |")


def main() -> None:
    builds = load(sys.argv[1] if len(sys.argv) > 1 else None)
    for label, scenarios in builds.items():
        any_r = next(iter(scenarios.values()))
        dev = any_r['device']
        print(f"### {label}\n")
        print(f"{dev['device']}, Android API {dev['android_api']}, {dev['abi']}, "
              f"{dev['cores']} cores; app {dev['versionName']} ({dev['versionCode']})\n")
        print('| scenario | window | app CPU avg / p95 / max (% of one core) | RAM | frames (Flutter) | '
              'other processes (CPU time) |')
        print('|---|---|---|---|---|---|')
        for name in ORDER:
            if name in scenarios:
                print(row(scenarios[name]))
        print()
        print('CPU over time (one character per second or so, taller = busier):\n')
        print('```')
        for name in ORDER:
            r = scenarios.get(name)
            if r and 'cpu' in r:
                s = sparkline(r['cpu'].get('series_pct', []))
                print(f"{name:<22}{s}")
        print('```\n')
        print('Battery proxies:\n')
        print('| scenario | app CPU-s | wake lock | Wi-Fi rx | foreground | job runs |')
        print('|---|---|---|---|---|---|')
        for name in ORDER:
            r = scenarios.get(name)
            if r and 'battery_proxies' in r:
                b = r['battery_proxies']
                print(f"| {name} | {r['cpu']['app_cpu_seconds']} | "
                      f"{b.get('wakelock_s', 0):.0f} s | {b.get('wifi_rx_kb', 0):.0f} KB | "
                      f"{b.get('foreground_s', 0):.0f} s | {b.get('job_runs', 0)} |")
        print()


if __name__ == '__main__':
    main()
