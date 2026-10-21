# Build with the server/ folder as the context:
#   docker build -f encore-admin/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# openssl: the website makes itself a certificate the first time it starts (the sign-in window needs https, encore_admin/tls.py).
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY encore-admin/encore_admin /app/encore_admin

# Runs as the owner of the music files (the compose file sets PUID:PGID). It writes nothing but the sign-in windows' profile folders
# under /signin and its certificate under /data.
USER 1000:1000
EXPOSE 8800
ENTRYPOINT ["python", "-m", "encore_admin"]
