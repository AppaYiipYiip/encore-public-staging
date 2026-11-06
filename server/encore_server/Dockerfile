FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/data/home \
    ENCORE_DATA_DIR=/data \
    ENCORE_MUSIC_DIR=/music

# ffmpeg: remuxing and tagging kept songs (the keeper); ca-certificates: HTTPS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# The dependencies come FIRST, in a layer that depends on pyproject.toml alone: a change to the server's own code then rebuilds only the small layers below it,
# and `encore update` downloads a few MB instead of the ~240 MB of dependencies again (measured 6 Nov 2026: 429 s at about 1 MB/s for a change of code only).
# A placeholder package lets pip resolve and install the dependencies; the placeholder itself is removed again. The weekly rebuild with --no-cache still
# refreshes yt-dlp, on purpose (.github/workflows/server-image.yml).
COPY pyproject.toml /app/pyproject.toml
RUN mkdir encore_server && touch encore_server/__init__.py \
 && pip install --no-cache-dir ".[youtube]" \
 && pip uninstall -y encore-server \
 && rm -rf encore_server build ./*.egg-info
COPY encore_server /app/encore_server
# The installer's files travel inside the image, so what an installation runs always matches the version that was downloaded.
COPY deploy /app/deploy
# The server itself (its dependencies are already there): the package with its migrations.
RUN pip install --no-cache-dir --no-deps .

# One unprivileged user; the data folder and the music folder are mounted in.
# The entrypoint starts as root, makes /data writable for that user (a folder Docker created is root's), then drops to it.
RUN useradd --uid 1000 --create-home --home-dir /data/home encore && mkdir -p /data /music && chown -R 1000:1000 /data
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
VOLUME ["/data"]
EXPOSE 4533
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:4533/encore/api/v1/info', timeout=4).status == 200 else 1)"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "encore_server"]
