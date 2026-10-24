#!/usr/bin/env python3
"""Faults on purpose (docs/11 ADR-R41 T4): puts a Toxiproxy between the emulator and the dev server and takes the server away, and back, while a song is
being asked for or is playing. Prints a timeline and the numbers a walk record needs (docs/07 section 12); it does not decide pass or fail.

    python -I fault_walk.py pb-f7              the server is away when a song is tapped: the song waits, nothing hops, it plays by itself when the server is back
    python -I fault_walk.py pb-f8 [SECONDS]    the server goes away in the middle of a song (SECONDS, default 8, after the music stops), then comes back

Set-up once (the dev VM is `encore-dev`; the proxy listens on 4550 and forwards to the server's 4540):
    ssh encore-dev 'docker run -d --name toxiproxy --network host ghcr.io/shopify/toxiproxy:2.12.0 -host 127.0.0.1'
    ssh encore-dev 'curl -s -XPOST localhost:8474/proxies -d "{\\"name\\":\\"encore\\",\\"listen\\":\\"0.0.0.0:4550\\",\\"upstream\\":\\"127.0.0.1:4540\\"}"'
    the server's ENCORE_HOME_URL is http://192.168.50.133:4550 (else it tells the phone its direct address and the phone goes round the proxy),
    and the phone's only saved address is http://192.168.50.133:4550.

The phone must be signed in, on Home, with the album "The Dark Side of the Moon" among the tiles (its songs stream from the server). Owned songs only: no YouTube look-ups.
"""
import json
import subprocess
import sys
import time

import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import play_timing as pt  # noqa: E402

T0 = time.monotonic()
NOTICES = ("Waiting for your server", "Waiting for a connection", "Couldn't play", "Can't reach your server", "Playback stopped", "Taking too long")


def now():
    return time.monotonic() - T0


def proxy(enabled):
    body = json.dumps({"enabled": enabled})
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", "encore-dev", f"curl -s -XPOST localhost:8474/proxies/encore -d '{body}'"],
                         capture_output=True, text=True, timeout=30).stdout
    print(f"[{now():6.1f}s] proxy {'UP  ' if enabled else 'DOWN'} -> {'enabled' if json.loads(out)['enabled'] else 'disabled'}", flush=True)


def toxic_limit(nbytes):
    """Each connection to the server is cut after `nbytes` of the answer (a song then has only its first seconds in the phone's buffer)."""
    body = json.dumps({"name": "cut", "type": "limit_data", "stream": "downstream", "toxicity": 1.0, "attributes": {"bytes": nbytes}})
    subprocess.run(["ssh", "-o", "BatchMode=yes", "encore-dev", f"curl -s -XPOST localhost:8474/proxies/encore/toxics -d '{body}' >/dev/null"], timeout=30)
    print(f"[{now():6.1f}s] toxic: every connection is cut after {nbytes} bytes", flush=True)


def toxic_clear():
    subprocess.run(["ssh", "-o", "BatchMode=yes", "encore-dev", "curl -s -XDELETE localhost:8474/proxies/encore/toxics/cut >/dev/null"], timeout=30)


def notices_on_screen():
    found = []
    for label, _x, _y, _c in pt.screen():
        for n in NOTICES:
            if n.lower() in label.lower() and label not in found:
                found.append(label)
    return found


def sample(until, seconds, every=0.2, screen_every=3.0):
    """Reads the player until `until(state)` is true or `seconds` pass; prints each change. Returns (last state, time it became true or None).
    The player is read as often as it answers (about every 0.7 s); the screen, which costs about 3 s a read, only every `screen_every` seconds, so
    the times of things the player shows (audible again) are good to about a second and the times of things only the screen shows to `screen_every`."""
    end = time.monotonic() + seconds
    last = None
    notes = []
    screen_read = 0.0
    while time.monotonic() < end:
        state, position, title, audible = pt.player_state()
        if time.monotonic() - screen_read >= screen_every:
            notes = notices_on_screen()
            screen_read = time.monotonic()
        key = (state, audible, title[:24], tuple(notes))
        if key != last:
            print(f"[{now():6.1f}s] player {state:9s} audible={audible!s:5s} pos={position / 1000:6.1f}s  '{title[:40]}'  screen: {notes or '-'}", flush=True)
            last = key
        if until(state, audible, title, notes):
            return (state, position, title, audible, notes), now()
        time.sleep(every)
    return (state, position, title, audible, notes), None


def hopped(title, expected):
    return expected.lower() not in title.lower()


def tap_song(name, album="The Dark Side of the Moon"):
    """From Home, opens the album tile and taps the song's row (an album of this server, so the song streams from it)."""
    pt.adb("shell", "input", "tap", "120", "1502")  # the Home tab
    tile = pt.wait_for(album, 15)
    if not tile:
        raise SystemExit(f"{album} is not on Home")
    pt.adb("shell", "input", "tap", str(tile[1]), str(tile[2]))
    row = pt.wait_for(name, 15)
    if not row:
        raise SystemExit(f"{name} is not listed on the album")
    print(f"[{now():6.1f}s] tap '{name}'", flush=True)
    pt.adb("shell", "input", "tap", str(row[1]), str(row[2]))


def pb_f7():
    song = "Breathe"
    proxy(False)
    time.sleep(1)
    tap_song(song)
    t_tap = now()
    got, t_wait = sample(lambda s, a, t, n: any("Waiting for your server" in x for x in n), 45)
    print(f"RESULT waiting notice after {t_wait - t_tap:.1f} s" if t_wait else "RESULT no 'Waiting for your server' notice within 45 s", flush=True)
    got, _ = sample(lambda s, a, t, n: False, 8)  # stay away for 8 more seconds: nothing may hop
    print(f"RESULT after 8 s more: title '{got[2][:30]}' hopped={hopped(got[2], song)} errors={[n for n in got[4] if 'Couldn' in n or 'stopped' in n]}", flush=True)
    proxy(True)
    t_back = now()
    got, t_audible = sample(lambda s, a, t, n: s == "PLAYING" and a and song.lower() in t.lower(), 60)
    print(f"RESULT audible {t_audible - t_back:.1f} s after the server was back" if t_audible else "RESULT never audible within 60 s of the server being back", flush=True)


def pb_f8(away=8):
    song = "Brain Damage"
    proxy(True)
    toxic_limit(300000)  # 300 kB is about 17 s of the song: without this a short song is buffered to its end and nothing can stall
    tap_song(song)
    _got, t_audible = sample(lambda s, a, t, n: s == "PLAYING" and a and song.lower() in t.lower(), 30)
    if not t_audible:
        raise SystemExit("the song never became audible: nothing to cut")
    time.sleep(3)
    proxy(False)
    t_down = now()
    got, t_stall = sample(lambda s, a, t, n: s != "PLAYING" or any("Waiting" in x for x in n), 150)
    if not t_stall:
        print("RESULT NOT RUN: the music never stopped within 150 s (the song was buffered to its end)", flush=True)
        proxy(True)
        return
    stalled_at = got[1] / 1000
    print(f"RESULT music stopped {t_stall - t_down:.1f} s after the server went away, at {stalled_at:.1f} s into the song", flush=True)
    sample(lambda s, a, t, n: False, away)
    got, _ = sample(lambda s, a, t, n: False, 0.5)
    print(f"RESULT while away: title '{got[2][:30]}' hopped={hopped(got[2], song)} screen={got[4]}", flush=True)
    proxy(True)
    t_back = now()
    got, t_again = sample(lambda s, a, t, n: s == "PLAYING" and a and song.lower() in t.lower(), 90)
    if t_again:
        print(f"RESULT audible again {t_again - t_back:.1f} s after the server was back, at {got[1] / 1000:.1f} s into the song (stopped at {stalled_at:.1f} s)", flush=True)
    else:
        print("RESULT never audible again within 90 s", flush=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if which == "pb-f7":
            pb_f7()
        elif which == "pb-f8":
            pb_f8(float(sys.argv[2]) if len(sys.argv) > 2 else 8)
        else:
            raise SystemExit(__doc__)
    finally:
        toxic_clear()
        proxy(True)  # never leave the server away
