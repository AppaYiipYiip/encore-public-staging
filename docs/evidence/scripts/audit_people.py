"""A day with twenty people on ONE Encore server (6 Nov 2026): English, French, Arabic, Russian and Chinese libraries, all at once, with very long items
(a two-hour recitation of Surat Al-Baqarah, a three-hour audiobook). The real server code behind a real socket, the real keeper behind a fake YouTube,
the real scheduler. Nothing is sent anywhere, no Docker: YouTube, the music server and the picture look-up (the keeper asks Deezer for a cover on every
keep; without the stub below, a run of this script would send hundreds of searches there, as its first three runs did) are replaced.

    C:/dev/venv-encore-server/Scripts/python.exe -X utf8 docs/evidence/scripts/audit_people.py [--people 20] [--seconds 20] [--server server/encore_server]

Every check prints PASS or FAIL with what was measured, and the register row it proves or reopens. A fix is done when its line says PASS. The script
speaks only the server's HTTP API (docs/17), so it is also what any other client (a tablet, a TV, a browser) has to be able to rely on.

    S1 scripts   twenty libraries in five scripts: are different songs told apart, does each person get THEIR song back, do two spellings of one song meet?
    S2 crowd     all twenty at once for N seconds: how long does a plain read take while others write, like, make playlists and ask for songs?
    S3 fair      one person asks the server to keep 260 songs, another then asks for 20: where do the 20 run?
    S4 long      a 2 h 13 min recitation, a 3 h audiobook, a 70 min mix, a 45:00 and a 45:01 song: what does the server keep, and what does each person see?
    S5 chaos     ONE account on three devices doing conflicting things at the same moment (one name three times, one id sent twice, rename against rename,
                 delete against edit, like against unlike, two devices writing the playback state) while the other nineteen people keep writing
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import threading
import time
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # a Windows console is cp1252 by default; this prints Arabic

V1 = "/encore/api/v1"

# --------------------------------------------------------------------------------------------------------------------------------- the cast
# (name, script). The first is the Host (the music server's administrator); the others are members.
CAST = (
    [(n, "en") for n in ("amy", "ben", "cara", "dan", "eve", "finn", "gus")]
    + [(n, "fr") for n in ("hugo", "ines", "jules", "lea", "marc")]
    + [(n, "ar") for n in ("noor", "omar", "layla", "karim", "salma")]
    + [(n, "ru") for n in ("pavel", "olga")]
    + [(n, "zh") for n in ("wei",)]
)
WORDS = {
    "en": (
        ["Midnight", "Paper", "Golden", "Quiet", "Broken", "Electric", "Summer", "Hollow"],
        ["Highway", "Garden", "Radio", "Letters", "Ocean", "Shadows", "Fire", "Morning"],
        ["Marlowe Reed", "Ada North", "Cold Harbour", "June Parker", "Silver Lanes", "Tom Wilder", "Iris Vale"],
    ),
    "fr": (
        ["Café", "Été", "Cœur", "Étoile", "Nuit", "Rêve", "Soleil", "Hôtel"],
        ["de Paris", "perdu", "d'automne", "sur la Seine", "éternel", "à Montréal", "du matin", "secret"],
        ["Édith Moreau", "Jean-Luc Girard", "Chloé Lambert", "Étienne Roux", "Zoé Marchand"],
    ),
    "ar": (
        ["حبيتك", "ليل", "قهوة", "سلام", "بحر", "وطني", "نسيم", "شوق"],
        ["بالصيف", "القاهرة", "الصباح", "يا حبيبي", "الغريب", "الأخير", "في المدينة", "القديم"],
        ["فيروز", "ماجدة الرومي", "كاظم الساهر", "وردة الجزائرية", "أم كلثوم"],
    ),
    "ru": (
        ["Звезда", "Ночь", "Дорога", "Кукушка", "Город", "Зима", "Весна", "Река"],
        ["любви", "над Москвой", "без тебя", "на рассвете", "огня", "мечты", "домой", "прощание"],
        ["Кино", "Аквариум"],
    ),
    "zh": (
        ["月亮", "夜曲", "童年", "青花瓷", "晴天", "稻香", "海阔", "天空"],
        ["代表我的心", "之歌", "的故事", "回忆", "与你", "的远方", "蓝色", "最后"],
        ["周杰伦"],
    ),
}
SONGS_EACH = 40


def library_of(name: str, script: str) -> list[dict]:
    """Forty different songs by this person's own artist, in their script. Durations differ by a few seconds, as real songs do."""
    firsts, seconds, artists = WORDS[script]
    mine = [n for n, s in CAST if s == script]
    k = mine.index(name)
    artist = artists[k % len(artists)]
    combos = [(a, b) for a in firsts for b in seconds]
    start = (k * 13) % len(combos)
    out = []
    for i in range(SONGS_EACH):
        a, b = combos[(start + i) % len(combos)]
        out.append({"title": f"{a} {b}", "artists": [artist], "durationMs": (150 + (i * 7 + k * 3) % 180) * 1000})
    return out


class Results:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str, str]] = []

    def check(self, ok: bool, name: str, detail: str, row: str = "") -> None:
        self.rows.append((ok, name, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}" + (f"   [{row}]" if row else ""))


def percentile(values: list[float], q: float) -> float:
    v = sorted(values)
    return v[min(len(v) - 1, int(len(v) * q))]


# --------------------------------------------------------------------------------------------------------------------------------- the server
def start_server(server: Path):
    sys.path.insert(0, str(server))
    import httpx  # noqa: PLC0415
    import uvicorn  # noqa: PLC0415

    import encore_server.keeper.keeper as keeper_module  # noqa: PLC0415
    from encore_server.api import create_app  # noqa: PLC0415
    from encore_server.config import Settings  # noqa: PLC0415
    from tests.conftest import FakeVerifier  # noqa: PLC0415
    from tests.test_keeper import FakeNavidrome, FakeSource, fake_ffmpeg  # noqa: PLC0415

    class Crowd(FakeVerifier):
        def __init__(self) -> None:
            super().__init__()
            self.passwords = {n: f"pw-{n}" for n, _ in CAST}
            self.admins = {CAST[0][0]}

    class Configured(FakeNavidrome):
        configured = True

    import functools  # noqa: PLC0415

    import encore_server.api as api_module  # noqa: PLC0415

    keeper_module.run_command = fake_ffmpeg  # no ffmpeg on the machine: the fake copies the bytes
    # the fake music server answers at once: do not wait half a second between looks, so 450 songs take seconds, not minutes
    api_module.KeepSettings = functools.partial(keeper_module.KeepSettings, scan_poll_s=0.01)
    api_module.deezer_lookup = lambda artist, title, album: None  # the keeper's cover look-up is a REAL call to Deezer: not here
    tmp = Path(tempfile.mkdtemp())
    (tmp / "music").mkdir()
    settings = Settings(
        data_dir=tmp / "data", music_dir=tmp / "music", navidrome_url="http://navidrome.invalid", youtube=False, workers=False, min_free_gb=0.0
    )
    source = FakeSource()
    app = create_app(settings, verifier=Crowd(), youtube=source, navidrome=Configured(tmp / "music"))
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False)
    server_ = uvicorn.Server(config)
    threading.Thread(target=server_.run, daemon=True).start()
    while not server_.started:
        time.sleep(0.05)
    port = server_.servers[0].sockets[0].getsockname()[1]
    return httpx, server_, app, source, f"http://127.0.0.1:{port}"


def phone(httpx, base: str, name: str):
    c = httpx.Client(base_url=base, timeout=60)
    login = c.post(f"{V1}/auth/login", json={"username": name, "password": f"pw-{name}", "deviceName": "sim"}).json()
    c.headers["Authorization"] = f"Bearer {login['deviceToken']}"
    return c


def in_threads(jobs) -> None:
    threads = [threading.Thread(target=j) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# --------------------------------------------------------------------------------------------------------------------------------- S1
def s1_scripts(httpx, base: str, people: list[tuple[str, str]], phones: dict, res: Results) -> dict[str, list[str]]:
    print("\nS1 scripts: twenty libraries, five scripts")
    got: dict[str, list[tuple[dict, dict]]] = {}  # name -> [(asked, answered)]

    def job(name: str, script: str):
        def run():
            asked = library_of(name, script)
            r = phones[name].post(f"{V1}/refs/resolve", json={"songs": asked})
            got[name] = list(zip(asked, r.json()["items"]))
        return run

    in_threads([job(n, s) for n, s in people])
    refs_of: dict[str, list[str]] = {}
    for script in WORDS:
        names = [n for n, s in people if s == script]
        if not names:
            continue
        ids = {a["id"] for n in names for _, a in got[n]}
        expected = len(names) * SONGS_EACH
        wrong = sum(1 for n in names for asked, a in got[n] if a["title"] != asked["title"] or a["artists"][0] != asked["artists"][0])
        res.check(
            len(ids) == expected and wrong == 0,
            f"{script}: {len(names)} people x {SONGS_EACH} different songs",
            f"{len(ids)} songs on the server (wanted {expected}); {wrong} of {len(names) * SONGS_EACH} asked-for songs came back as ANOTHER song",
            "B-37",
        )
        refs_of[script] = [a["id"] for n in names for _, a in got[n]]

    non_latin = [i for sc in ("ar", "ru", "zh") if sc in refs_of for i in refs_of[sc]]
    want = sum(len([n for n, s in people if s == sc]) * SONGS_EACH for sc in ("ar", "ru", "zh") if sc in refs_of)
    res.check(
        len(set(non_latin)) == want,
        "Arabic, Russian and Chinese libraries together: different songs of different languages stay different",
        f"{len(set(non_latin))} songs for {want} asked (a Russian song, an Arabic song and a Chinese song of the same length are ONE song today)",
        "B-37",
    )
    # two spellings of ONE song must meet; two different songs of one artist must not
    c = phones["amy"]

    def one(item: dict) -> str:
        return c.post(f"{V1}/refs/resolve", json={"songs": [item]}).json()["items"][0]["id"]

    def pair(a: dict, b: dict) -> bool:
        return one(a) == one(b)

    base_fr = {"title": "Café de Flore", "artists": ["Édith Moreau"], "durationMs": 214000}
    nfd = unicodedata.normalize("NFD", base_fr["title"])
    res.check(pair(base_fr, {**base_fr, "title": nfd}), "French: the same song typed with a composed and a decomposed accent", "one song wanted", "text")
    marks = pair(
        {"title": "حَبَيْتُكَ بِالصَّيْفِ", "artists": ["فيروز"], "durationMs": 181000},
        {"title": "حبيتك بالصيف", "artists": ["فيروز"], "durationMs": 181000},
    )
    res.check(
        pair(
            {"title": "أغنية ١٢", "artists": ["فيروز"], "durationMs": 200000},
            {"title": "أغنية 12", "artists": ["فيروز"], "durationMs": 200000},
        ),
        "Arabic: the same song with Arabic-Indic and Western digits",
        "one song wanted",
        "text",
    )
    different = not pair(
        {"title": "ليل القاهرة", "artists": ["فيروز"], "durationMs": 200000},
        {"title": "قهوة الصباح", "artists": ["فيروز"], "durationMs": 200000},
    )
    res.check(
        marks and different,
        "Arabic: the same song with and without the vowel marks meets, and only that one",
        f"{'one song' if marks else 'two songs'} for the two spellings; and it only counts if different songs stay different ({'they do' if different else 'they do NOT: everything of this length merges, so a merge proves nothing'})",
        "text",
    )
    res.check(different, "Arabic: two DIFFERENT songs of one artist, the same length, stay two songs", "two songs wanted", "B-37")
    ru = not pair(
        {"title": "Звезда любви", "artists": ["Кино"], "durationMs": 230000}, {"title": "Ночь над Москвой", "artists": ["Кино"], "durationMs": 230000}
    )
    res.check(ru, "Russian: two different songs of one artist, the same length, stay two songs", "two songs wanted", "B-37")
    zh = not pair({"title": "晴天", "artists": ["周杰伦"], "durationMs": 269000}, {"title": "稻香", "artists": ["周杰伦"], "durationMs": 269000})
    res.check(zh, "Chinese: two different songs of one artist, the same length, stay two songs", "two songs wanted", "B-37")
    return refs_of


# --------------------------------------------------------------------------------------------------------------------------------- S2
def s2_crowd(httpx, base: str, people, phones, refs_of, seconds: float, res: Results) -> None:
    from encore_server.ids import new_id  # noqa: PLC0415

    print(f"\nS2 crowd: {len(people)} people at once for {seconds:.0f} s")
    samples: dict[str, list[float]] = {}
    errors: list[str] = []
    lock = threading.Lock()
    stop = time.monotonic() + seconds
    ready = threading.Barrier(len(people) + 1)

    def timed(c, kind, method, path, **kw):
        t = time.perf_counter()
        try:
            r = c.request(method, path, **kw)
            code = r.status_code
        except Exception as e:  # noqa: BLE001
            with lock:
                errors.append(f"{kind}: {type(e).__name__}")
            return None
        ms = (time.perf_counter() - t) * 1000
        with lock:
            samples.setdefault(kind, []).append(ms)
            if code >= 500:
                errors.append(f"{kind}: {code}")
        return r

    def person(name: str, script: str):
        def run():
            c = phones[name]
            mine = [a["id"] for a in library_of_cached[name]]
            ready.wait()
            n = 0
            while time.monotonic() < stop:
                n += 1
                timed(c, "read: library feed", "GET", f"{V1}/library/changes", params={"since": "0"})
                timed(c, "read: playlists", "GET", f"{V1}/playlists")
                timed(c, "read: how my downloads go", "POST", f"{V1}/keep/progress", json={"groups": [{"kind": "liked", "id": "liked"}]})
                timed(c, "read: a song's signed address", "GET", f"{V1}/refs/{mine[n % len(mine)]}/stream-url")
                timed(c, "write: playback position", "PUT", f"{V1}/playback", json={"ref": mine[n % len(mine)], "positionMs": 1000 * n, "playing": True, "rev": 0})
                timed(c, "write: a like", "PUT", f"{V1}/likes/{mine[n % len(mine)]}")
                if n % 5 == 0:
                    timed(c, "write: a new playlist", "POST", f"{V1}/playlists", json={"id": new_id("pl"), "name": f"mix {n}"})
                time.sleep(0.1)
        return run

    library_of_cached = {}
    for name, script in people:
        asked = library_of(name, script)
        library_of_cached[name] = phones[name].post(f"{V1}/refs/resolve", json={"songs": asked}).json()["items"]
    threads = [threading.Thread(target=person(n, s)) for n, s in people]
    for t in threads:
        t.start()
    ready.wait()
    began = time.monotonic()
    for t in threads:
        t.join()
    took = time.monotonic() - began
    total = sum(len(v) for v in samples.values())
    print(f"  {total} calls in {took:.0f} s ({total / took:.0f} a second)")
    print(f"  {'kind':<36}{'calls':>7}{'median':>9}{'p95':>9}{'max':>9}   (ms)")
    for kind in sorted(samples):
        v = samples[kind]
        print(f"  {kind:<36}{len(v):>7}{statistics.median(v):>9.1f}{percentile(v, 0.95):>9.1f}{max(v):>9.1f}")
    reads = [x for k, v in samples.items() if k.startswith("read") for x in v]
    p95 = percentile(reads, 0.95)
    worst = max(reads)
    res.check(not errors, "no call failed", f"{len(errors)} failures {sorted(set(errors))[:3]}", "stability")
    res.check(p95 < 500 and worst < 2000, "a plain read stays quick while others write", f"p95 {p95:.0f} ms, slowest {worst:.0f} ms (wanted p95 < 500 ms, none > 2 s)", "B-10, B-18")


# --------------------------------------------------------------------------------------------------------------------------------- S3
def s3_fair(httpx, base: str, app, source, phones, res: Results) -> None:
    print("\nS3 fair: 260 songs asked by one person, then 20 by another")
    svc = app.state.services
    svc.scheduler.drain("background", limit=5000)  # what the earlier scenes left in the queue is not part of this measure
    a, b = phones["noor"], phones["hugo"]
    big = a.post(f"{V1}/refs/resolve", json={"songs": [{"title": f"Queue {n:03d}", "artists": ["Noor Long"], "durationMs": 200000 + n * 100} for n in range(260)]}).json()["items"]
    small = b.post(f"{V1}/refs/resolve", json={"songs": [{"title": f"Court {n:02d}", "artists": ["Hugo Court"], "durationMs": 210000 + n * 100} for n in range(20)]}).json()["items"]
    for r in big:
        a.put(f"{V1}/likes/{r['id']}")
        time.sleep(0.001)
    for r in small:
        b.put(f"{V1}/likes/{r['id']}")
    source.asked.clear()
    began = time.perf_counter()
    svc.scheduler.drain("background", limit=1000)
    took = time.perf_counter() - began
    order = [w.title for w in source.asked]
    positions = [i + 1 for i, t in enumerate(order) if t.startswith("Court")]
    # Taking turns would put the 20 at about every second position, so within the first 40; the bar is 60. The scheduler looks at the first 200 queued
    # items before it shares the turn, so the 20 only come in once the first person's backlog is under 200: after 60 of the 260.
    res.check(
        bool(positions) and positions[0] <= 5 and max(positions) <= 60,
        "the second person's 20 songs take their turn at once, not after the first person's backlog has shrunk",
        f"the 20 ran at positions {positions[0] if positions else '-'} to {max(positions) if positions else '-'} of {len(order)} (wanted: the first within 5, all within 60); {took:.1f} s for {len(order)} songs",
        "B-39, P3-32",
    )


# --------------------------------------------------------------------------------------------------------------------------------- S4
def s4_long(httpx, base: str, app, source, phones, res: Results) -> None:
    print("\nS4 long: a 2 h 13 min recitation, a 3 h audiobook, a 70 min mix, and the 45-minute line")
    svc = app.state.services
    items = [
        ("سورة البقرة", "مشاري راشد العفاسي", 7_980_000, "Surat Al-Baqarah, 2 h 13 min"),
        ("The Count of Monte Cristo (complete)", "Alexandre Dumas", 10_800_000, "an audiobook, 3 h"),
        ("Midnight Radio Mix", "DJ Cassini", 4_200_000, "a DJ mix, 70 min"),
        ("Forty Five Exactly", "Edge Case", 2_700_000, "45:00 exactly"),
        ("Forty Five and One", "Edge Case", 2_701_000, "45:01"),
        ("Plain Song", "Ordinary Artist", 215_000, "a normal 3 min 35 s song"),
    ]
    host, member = phones["amy"], phones["layla"]
    made = []
    for title, artist, ms, label in items:
        r = member.post(f"{V1}/refs/resolve", json={"songs": [{"title": title, "artists": [artist], "durationMs": ms}]}).json()["items"][0]
        made.append((r, label, ms))
        res.check(r["durationMs"] == ms and r["title"] == title, f"{label}: the server keeps its length and its name as given", f"{r['durationMs'] / 60000:.0f} min", "text")
        member.put(f"{V1}/likes/{r['id']}")
        host.put(f"{V1}/likes/{r['id']}")
    svc.scheduler.drain("background", limit=100)
    mine = member.post(f"{V1}/keep/progress", json={"groups": [{"kind": "liked", "id": "liked"}]}).json()["groups"][0]
    boss = host.post(f"{V1}/keep/progress", json={"groups": [{"kind": "liked", "id": "liked"}]}).json()["groups"][0]
    by_member = {f["ref"]: f for f in mine["failures"]}
    by_host = {f["ref"]: f for f in boss["failures"]}
    for r, label, ms in made:
        kept = r["id"] not in by_member
        f = by_member.get(r["id"])
        hf = by_host.get(r["id"])
        say = "kept" if kept else f"not kept; the member reads: \"{f['reason']}\" (Retry {'offered' if f['retry'] else 'not offered'}); the Host reads: \"{hf['reason']}\""
        res.check(kept, f"{label}: kept on the server, so it can be downloaded", say, "B-94")
    stream = member.get(f"{V1}/refs/{made[0][0]['id']}/stream-url").json()
    res.check(stream["expiresAt"] / 1000 - time.time() > 7980 + 600, "the signed address of the 2 h 13 min recitation outlasts the recitation", f"valid for {(stream['expiresAt'] / 1000 - time.time()) / 3600:.1f} h", "ok")
    mb = 7980 * 128_000 / 8 / 1_048_576
    print(f"  (size: 2 h 13 min at 128 kbit/s is about {mb:.0f} MB; the keeper refuses more than 80 MB and more than 45 minutes, so a recitation of this length is refused twice over)")


# --------------------------------------------------------------------------------------------------------------------------------- S5
def race(*calls):
    """Runs the calls at the same moment (all released together) and returns (status, json, ms) for each, in order."""
    gate = threading.Barrier(len(calls))
    out: list = [None] * len(calls)

    def run(i, call):
        gate.wait()
        t = time.perf_counter()
        try:
            r = call()
            try:
                body = r.json()
            except ValueError:
                body = None
            out[i] = (r.status_code, body, (time.perf_counter() - t) * 1000)
        except Exception as e:  # noqa: BLE001
            out[i] = (599, {"error": f"{type(e).__name__}: {e}"}, (time.perf_counter() - t) * 1000)

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def s5_chaos(httpx, base: str, people, phones, res: Results) -> None:
    from encore_server.ids import new_id  # noqa: PLC0415

    print("\nS5 chaos: one account on three devices, conflicting things at the same moment, while the others keep writing")
    d1, d2, d3 = (phone(httpx, base, "amy") for _ in range(3))
    refs = d1.post(f"{V1}/refs/resolve", json={"songs": library_of("amy", "en")[:6]}).json()["items"]
    r0, r1, r2 = refs[0]["id"], refs[1]["id"], refs[2]["id"]

    # the other nineteen keep writing the whole time
    stop = threading.Event()
    others = [(n, s) for n, s in people if n != "amy"]
    other_refs = {n: [a["id"] for a in phones[n].post(f"{V1}/refs/resolve", json={"songs": library_of(n, s)[:10]}).json()["items"]] for n, s in others}
    writes: list[float] = []

    def noise(name: str):
        c, mine, n = phones[name], other_refs[name], 0
        while not stop.is_set():
            n += 1
            for call in (
                lambda: c.put(f"{V1}/likes/{mine[n % len(mine)]}"),
                lambda: c.post(f"{V1}/playlists", json={"id": new_id("pl"), "name": f"mix {n}"}),
                lambda: c.put(f"{V1}/playback", json={"ref": mine[n % len(mine)], "positionMs": n, "playing": True, "rev": 0}),
            ):
                t = time.perf_counter()
                try:
                    call()
                except Exception:  # noqa: BLE001
                    pass
                writes.append((time.perf_counter() - t) * 1000)
            time.sleep(0.02)

    noisy = [threading.Thread(target=noise, args=(n,), daemon=True) for n, _ in others]
    for t in noisy:
        t.start()
    time.sleep(0.5)

    five_xx: list[str] = []
    slow: list[float] = []

    def note(label: str, rows) -> None:
        for code, _, ms in rows:
            slow.append(ms)
            if code >= 500:
                five_xx.append(f"{label}: {code}")

    def playlists(c):
        return {p["id"]: p["name"] for p in c.get(f"{V1}/playlists").json()["items"]}

    def entries_of(c, pid):
        body = c.get(f"{V1}/playlists/{pid}").json()
        return body.get("entries") or body.get("songs") or []

    # 1. three playlists with the same name, made at the same moment on three devices
    rows = race(
        lambda: d1.post(f"{V1}/playlists", json={"id": new_id("pl"), "name": "Road trip"}),
        lambda: d2.post(f"{V1}/playlists", json={"id": new_id("pl"), "name": "Road trip"}),
        lambda: d3.post(f"{V1}/playlists", json={"id": new_id("pl"), "name": "Road trip"}),
    )
    note("same name", rows)
    seen = [sorted(n for n in playlists(c).values() if n == "Road trip") for c in (d1, d2, d3)]
    res.check(
        all(len(x) == 3 for x in seen) and all(r[0] == 201 for r in rows),
        "three devices make a playlist called 'Road trip' at the same moment",
        f"statuses {[r[0] for r in rows]}; each device then sees {[len(x) for x in seen]} playlists with that name (wanted three, all created: one name twice is allowed)",
        "CF",
    )

    # 2. the same playlist id sent twice (a retry, a double tap on two devices)
    pid = new_id("pl")
    rows = race(
        lambda: d1.post(f"{V1}/playlists", json={"id": pid, "name": "Gym"}),
        lambda: d2.post(f"{V1}/playlists", json={"id": pid, "name": "Gym"}),
    )
    note("same id", rows)
    count = sum(1 for i in playlists(d3) if i == pid)
    res.check(count == 1 and all(r[0] < 500 for r in rows), "one playlist id sent from two devices at the same moment", f"statuses {[r[0] for r in rows]}; {count} playlist with that id (wanted exactly one, no server error)", "CF")

    # 3. the same song into one playlist from three devices; and one entry id sent twice
    rows = race(
        lambda: d1.post(f"{V1}/playlists/{pid}/entries", json={"songs": [{"ref": r0, "id": new_id("pe")}]}),
        lambda: d2.post(f"{V1}/playlists/{pid}/entries", json={"songs": [{"ref": r0, "id": new_id("pe")}]}),
        lambda: d3.post(f"{V1}/playlists/{pid}/entries", json={"songs": [{"ref": r0, "id": new_id("pe")}]}),
    )
    note("same song", rows)
    views = [[e.get("id") for e in entries_of(c, pid)] for c in (d1, d2, d3)]
    res.check(
        views[0] == views[1] == views[2] and len(views[0]) == 3 and len(set(views[0])) == 3,
        "the same song added to one playlist from three devices at once",
        f"statuses {[r[0] for r in rows]}; each device sees {[len(v) for v in views]} entries, same order on all: {views[0] == views[1] == views[2]} (wanted three: a song twice is the person's choice)",
        "CF",
    )
    same_entry = new_id("pe")
    rows = race(
        lambda: d1.post(f"{V1}/playlists/{pid}/entries", json={"songs": [{"ref": r1, "id": same_entry}]}),
        lambda: d2.post(f"{V1}/playlists/{pid}/entries", json={"songs": [{"ref": r1, "id": same_entry}]}),
    )
    note("same entry id", rows)
    n_same = sum(1 for e in entries_of(d3, pid) if e.get("id") == same_entry)
    res.check(n_same == 1 and all(r[0] < 500 for r in rows), "one entry id sent from two devices (a retry)", f"statuses {[r[0] for r in rows]}; {n_same} entry with that id (wanted exactly one)", "CF")

    # 4. rename against rename: the last to arrive wins and every device agrees
    rows = race(
        lambda: d1.patch(f"{V1}/playlists/{pid}", json={"name": "Alpha"}),
        lambda: d2.patch(f"{V1}/playlists/{pid}", json={"name": "Beta"}),
        lambda: d3.patch(f"{V1}/playlists/{pid}", json={"name": "Gamma"}),
    )
    note("rename", rows)
    final = [playlists(c).get(pid) for c in (d1, d2, d3)]
    res.check(len(set(final)) == 1 and final[0] in ("Alpha", "Beta", "Gamma"), "three devices rename one playlist at the same moment", f"every device shows {final} (one of the three: last to arrive wins, CF-20)", "CF-20")

    # 5. delete against edit
    rows = race(
        lambda: d1.delete(f"{V1}/playlists/{pid}"),
        lambda: d2.post(f"{V1}/playlists/{pid}/entries", json={"songs": [{"ref": r2, "id": new_id("pe")}]}),
        lambda: d3.patch(f"{V1}/playlists/{pid}", json={"name": "Too late"}),
    )
    note("delete vs edit", rows)
    gone = [pid not in playlists(c) for c in (d1, d2, d3)]
    res.check(all(gone) and all(r[0] < 500 for r in rows), "one device deletes a playlist while two others edit it", f"statuses {[r[0] for r in rows]}; gone on all three devices: {gone} (delete wins, the late edits answer 'not found', CF-21)", "CF-21")

    # 6. like against unlike, three devices, fifteen rounds
    d1.delete(f"{V1}/likes/{r0}")
    count = lambda d: d.post(f"{V1}/keep/progress", json={"groups": [{"kind": "liked", "id": "liked"}]}).json()["groups"][0]["total"]  # noqa: E731
    before = count(d1)  # this account may already like other songs
    wrong = []
    for _ in range(15):
        rows = race(
            lambda: d1.put(f"{V1}/likes/{r0}"),
            lambda: d2.delete(f"{V1}/likes/{r0}"),
            lambda: d3.put(f"{V1}/likes/{r0}"),
        )
        note("like flapping", rows)
        wrong += [r[0] for r in rows if r[0] >= 500]
    liked = [count(d) - before for d in (d1, d2, d3)]
    res.check(not wrong and len(set(liked)) == 1 and liked[0] in (0, 1), "like and unlike of one song from three devices, fifteen rounds", f"{len(wrong)} server errors; all devices end with the same answer ({liked} liked)", "CF")

    # 7. the playback state: two devices write the same revision
    rev = d1.get(f"{V1}/playback").json()["state"]["rev"]  # the account may already have a state (the earlier scenes wrote one)
    rows = race(
        lambda: d1.put(f"{V1}/playback", json={"ref": r0, "positionMs": 1000, "playing": True, "rev": rev}),
        lambda: d2.put(f"{V1}/playback", json={"ref": r1, "positionMs": 2000, "playing": True, "rev": rev}),
    )
    note("playback", rows)
    codes = sorted(r[0] for r in rows)
    res.check(codes == [200, 409], "two devices write the playback state with the same revision", f"statuses {codes} (wanted one 200 and one 409 'conflict' with the current state, CF-41)", "CF-41")

    stop.set()
    for t in noisy:
        t.join(timeout=5)
    res.check(not five_xx, "no conflicting call made the server fail", f"{len(five_xx)} server errors {sorted(set(five_xx))[:3]} in {len(slow)} raced calls; the other nineteen made {len(writes)} writes meanwhile", "stability")
    res.check(max(slow) < 2000 and max(writes or [0]) < 2000, "nobody waits long while this goes on", f"slowest raced call {max(slow):.0f} ms; the others' slowest write {max(writes or [0]):.0f} ms, p95 {percentile(writes or [0], 0.95):.0f} ms (wanted none over 2 s)", "B-10, B-18")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--people", type=int, default=len(CAST))
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--server", type=Path, default=Path(__file__).resolve().parents[3] / "server" / "encore_server")
    parser.add_argument("only", nargs="?", choices=["scripts", "crowd", "fair", "long", "chaos"])
    args = parser.parse_args()
    people = CAST[: args.people]
    httpx, server_, app, source, base = start_server(args.server)
    phones = {n: phone(httpx, base, n) for n, _ in CAST}
    res = Results()
    refs_of = {}
    try:
        if args.only in (None, "scripts"):
            refs_of = s1_scripts(httpx, base, people, phones, res)
        if args.only in (None, "crowd"):
            s2_crowd(httpx, base, people, phones, refs_of, args.seconds, res)
        if args.only in (None, "fair"):
            s3_fair(httpx, base, app, source, phones, res)
        if args.only in (None, "long"):
            s4_long(httpx, base, app, source, phones, res)
        if args.only in (None, "chaos"):
            s5_chaos(httpx, base, people, phones, res)
    finally:
        server_.should_exit = True
    failed = [r for r in res.rows if not r[0]]
    print(f"\n{len(res.rows) - len(failed)} PASS, {len(failed)} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
