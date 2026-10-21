FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/work/home \
    PATH=/work/home/.local/bin:/usr/local/bin:/usr/bin:/bin

# ffmpeg: remux the downloaded stream (no re-encoding); ca-certificates: HTTPS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Deno: a signed-in YouTube account is served the browser-style player, whose address puzzles (signature and "n" challenge) yt-dlp can
# only solve with a JavaScript runtime. Without one every fetch as a signed-in account fails with "The page needs to be reloaded"
# (found on 2026-10-18 with the first real account; a visitor is served other clients and never noticed). yt-dlp turns Deno on by
# itself. (Debian's Node 20 is "unsupported" by the current yt-dlp.) See install_deno.py.
COPY install_deno.py /tmp/install_deno.py
RUN python /tmp/install_deno.py && rm /tmp/install_deno.py

# yt-dlp is also (re)installed at every start so a restart fixes the usual
# "YouTube changed something" breakages; this layer is the offline fallback. "[default]" brings yt-dlp-ejs (the solver scripts
# for those puzzles, tied to the yt-dlp version) and the other helpers.
RUN pip install --no-cache-dir "yt-dlp[default]" mutagen ytmusicapi

WORKDIR /app
COPY encore_fetch /app/encore_fetch
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# The music library in the media stack belongs to uid/gid 1000.
USER 1000:1000
EXPOSE 8701
ENTRYPOINT ["/entrypoint.sh"]
