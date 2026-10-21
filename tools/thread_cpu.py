"""Per-thread CPU of the app over a window: python tool/thread_cpu.py [seconds]

Reads /proc/<pid>/task/*/stat twice. Shows *which* thread burns the CPU
(main = Dart UI isolate, 1.raster, ExoPlayer:Playb, dart:io EventHa, ...) and
whether it is user or kernel time.
"""
import re
import shutil
import subprocess
import sys
import time

ADB = shutil.which('adb') or r'C:\dev\android-sdk\platform-tools\adb.exe'
PKG = 'app.encore.player'
secs = int(sys.argv[1]) if len(sys.argv) > 1 else 20


def sh(cmd):
    return subprocess.run([ADB, 'shell', cmd], capture_output=True, text=True).stdout.replace('\r', '')


def snap(pid):
    out = sh(f'for t in /proc/{pid}/task/*; do cat $t/stat; done')
    res = {}
    for line in out.splitlines():
        m = re.match(r'(\d+) \((.*)\) \S (.*)', line)
        if not m:
            continue
        rest = m.group(3).split()
        res[int(m.group(1))] = (m.group(2), int(rest[10]), int(rest[11]))
    return res


pid = int(sh(f'pidof -s {PKG}').strip())
a = snap(pid)
t0 = time.time()
time.sleep(secs)
b = snap(pid)
dt = time.time() - t0
rows = []
for tid, (name, u, s) in b.items():
    ua, sa = (a.get(tid, (name, 0, 0))[1], a.get(tid, (name, 0, 0))[2])
    d = (u - ua) + (s - sa)
    if d > 0:
        rows.append((d, name, tid, u - ua, s - sa))
rows.sort(reverse=True)
total = sum(r[0] for r in rows)
print(f'window {dt:.1f}s, process total {total / 100 / dt * 100:.1f}% of one core')
for d, name, tid, du, ds in rows[:14]:
    print(f'{d / 100 / dt * 100:5.1f}%  {name:<18} tid={tid} user={du / 100:.2f}s sys={ds / 100:.2f}s')
