"""Installs Deno (a JavaScript runtime) into /usr/local/bin while the image is built.

yt-dlp needs a JavaScript runtime to solve the "signature" and "n" puzzles in YouTube's player, which a signed-in YouTube account is
always served (docs/50: without it every fetch as an account fails with "The page needs to be reloaded"). Deno is the one yt-dlp
turns on by itself and the one found to work with the first real account; the Debian package of Node (20) is "unsupported" by the
current yt-dlp. Pinned, with the right download for this machine (Intel/AMD or ARM).
"""
import os
import platform
import stat
import urllib.request
import zipfile

VERSION = "v2.9.7"
ARCH = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(platform.machine().lower())
if ARCH is None:
    raise SystemExit(f"no Deno build known for {platform.machine()}")
URL = f"https://github.com/denoland/deno/releases/download/{VERSION}/deno-{ARCH}-unknown-linux-gnu.zip"
urllib.request.urlretrieve(URL, "/tmp/deno.zip")
with zipfile.ZipFile("/tmp/deno.zip") as archive:
    archive.extract("deno", "/usr/local/bin")
os.chmod("/usr/local/bin/deno", os.stat("/usr/local/bin/deno").st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
os.remove("/tmp/deno.zip")
print("deno", VERSION, ARCH)
