"""Type the password from a login file into the focused field on the emulator. Never prints it.

usage: python -I typepw.py LOGIN_FILE
"""
import os
import subprocess
import sys
import tempfile

ADB = r"C:\dev\android-sdk\platform-tools\adb.exe"
pw = None
for line in open(sys.argv[1], encoding="utf-8"):
    if line.lower().startswith("password:"):
        pw = line.split(":", 1)[1].strip()
if not pw:
    print("no password line"); sys.exit(1)
with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as f:
    f.write(pw.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`").replace(" ", "%s"))
    tmp = f.name
subprocess.run([ADB, "push", tmp, "/data/local/tmp/_t.txt"], capture_output=True)
os.unlink(tmp)
subprocess.run([ADB, "shell", 'input text "$(cat /data/local/tmp/_t.txt)"; rm -f /data/local/tmp/_t.txt'], capture_output=True)
print("typed (hidden)")
