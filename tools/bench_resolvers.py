"""Times the old and the lean song search side by side, on the machine and line it runs on (docs/tasks P1-01).

Run it INSIDE the fetch service's container (it needs the service's libraries):
    docker exec -i encore-fetch python3 - < tools/bench_resolvers.py

At most 3 songs, one resolution of each kind per song (see docs/06 section 8: never burst at YouTube). Prints stage times only.
"""
import statistics
import sys
import time

from encore_fetch.lean import LeanResolver, YtmusicApiSearcher
from encore_fetch.resolve import Want, YtDlpResolver

SONGS = [
    Want("Khruangbin", "Maria Tambien", "Con Todo El Mundo", 191),
    Want("Nas", "N.Y. State of Mind", "Illmatic", 294),
    Want("Fairuz", "Kifak Inta", "Kifak Inta", 212),
]

legacy = YtDlpResolver("yt-dlp")
lean = LeanResolver(YtmusicApiSearcher())
rows = []
for want in SONGS:
    out = {"song": f"{want.artist} - {want.title}"}
    for name, resolver in (("lean", lean), ("legacy", legacy)):
        t0 = time.monotonic()
        found = resolver.resolve(want)
        out[name] = round(time.monotonic() - t0, 2)
        out[name + "_pick"] = None if found is None else (found.candidate.track or found.candidate.title,
                                                          ", ".join(found.candidate.artists) or found.candidate.channel,
                                                          found.candidate.album)
    rows.append(out)
    time.sleep(3)

for r in rows:
    print(f"{r['song']:34} lean {r['lean']:5.2f} s   legacy {r['legacy']:5.2f} s")
    print(f"{'':34} lean picked   {r['lean_pick']}")
    print(f"{'':34} legacy picked {r['legacy_pick']}")
print(f"median: lean {statistics.median(r['lean'] for r in rows):.2f} s, legacy {statistics.median(r['legacy'] for r in rows):.2f} s",
      file=sys.stdout)
