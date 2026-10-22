#!/usr/bin/env python3
"""Drive the test emulator like a person (docs/12 journeys). Usage: python -I ui.py <command> [args]

  dump                    list what is on screen: text / content-desc, centre x,y, and * if clickable
  tap "text"              tap the first element whose text or description contains it (case-insensitive); tap "text" 2 = the 2nd
  tapxy X Y               tap a point
  swipe X1 Y1 X2 Y2 [ms]  swipe
  type "some text"        type into the focused field
  typefile PATH           type a password: the `password:` line of a login file, or the whole of a file that holds only the password; pushed, typed, deleted; never printed
  key BACK|TAB|ENTER|HOME|DOWN|UP|PLAY_PAUSE|MEDIA_NEXT|MEDIA_PREVIOUS
  shot NAME               save a screenshot to scratchpad/shots/NAME.png (never while a password is on screen)
  wait "text" [seconds]   wait until the text is on screen (default 20 s); exit 1 if it never shows
  gone "text" [seconds]   wait until the text is NOT on screen
"""
import os, re, subprocess, sys, tempfile, time
import xml.etree.ElementTree as ET

ADB = r"C:\dev\android-sdk\platform-tools\adb.exe"
DEV = ["-s", os.environ.get("ANDROID_SERIAL", "emulator-5556")]
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")


def adb(*a, text=True, check=False):
    return subprocess.run([ADB, *DEV, *a], capture_output=True, text=text, encoding="utf-8" if text else None, errors="replace" if text else None, check=check)


def dump():
    for _ in range(4):
        r = adb("exec-out", "uiautomator", "dump", "/dev/tty")
        out = r.stdout
        i, j = out.find("<?xml"), out.rfind("</hierarchy>")
        if i >= 0 and j > 0:
            return ET.fromstring(out[i:j + len("</hierarchy>")])
        time.sleep(0.7)
    raise SystemExit("could not read the screen")


def nodes():
    root = dump()
    res = []
    for n in root.iter("node"):
        label = (n.get("text") or "").strip() or (n.get("content-desc") or "").strip()
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds") or "")
        if not m:
            continue
        l, t, r, b = map(int, m.groups())
        res.append({"label": label.replace("\n", " | "), "x": (l + r) // 2, "y": (t + b) // 2,
                    "w": r - l, "h": b - t, "click": n.get("clickable") == "true", "cls": n.get("class", "")})
    return res


def find(sub, nth=1):
    hits = [n for n in nodes() if n["label"] and sub.lower() in n["label"].lower()]
    return hits[nth - 1] if len(hits) >= nth else None


def main():
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "dump":
        for n in nodes():
            if n["label"] or n["click"]:
                print(f"{'*' if n['click'] else ' '} ({n['x']:4},{n['y']:4}) {n['w']}x{n['h']}  {n['label'][:110]}")
    elif cmd == "tap":
        n = find(args[0], int(args[1]) if len(args) > 1 else 1)
        if not n:
            print("not on screen:", args[0]); sys.exit(1)
        adb("shell", "input", "tap", str(n["x"]), str(n["y"]))
        print(f"tapped '{n['label'][:60]}' at {n['x']},{n['y']}")
    elif cmd == "tapxy":
        adb("shell", "input", "tap", args[0], args[1])
    elif cmd == "swipe":
        adb("shell", "input", "swipe", *args[:4], *(args[4:5] or ["300"]))
    elif cmd == "type":
        adb("shell", "input", "text", args[0].replace(" ", "%s"))
    elif cmd == "typefile":
        raw = open(args[0], encoding="utf-8").read()
        # A login file (address / user / password lines) types only its password; any other file is typed whole.
        lines = [l for l in raw.splitlines() if l.lower().startswith("password:")]
        secret = lines[0].split(":", 1)[1].strip() if lines else raw.strip()
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write(secret); tmp = f.name
        adb("push", tmp, "/data/local/tmp/_t.txt"); os.unlink(tmp)
        adb("shell", 'input text "$(cat /data/local/tmp/_t.txt)"; rm -f /data/local/tmp/_t.txt')
        print("typed (hidden)")
    elif cmd == "key":
        adb("shell", "input", "keyevent", "KEYCODE_" + args[0].upper())
    elif cmd == "shot":
        os.makedirs(SHOTS, exist_ok=True)
        p = os.path.join(SHOTS, args[0] + ".png")
        with open(p, "wb") as f:
            f.write(adb("exec-out", "screencap", "-p", text=False).stdout)
        print(p)
    elif cmd in ("wait", "gone"):
        limit = float(args[1]) if len(args) > 1 else 20.0
        end = time.time() + limit
        while time.time() < end:
            seen = find(args[0]) is not None
            if (cmd == "wait") == seen:
                print("ok"); return
            time.sleep(1.0)
        print("timeout:", cmd, args[0]); sys.exit(1)
    else:
        print(__doc__)


main()
