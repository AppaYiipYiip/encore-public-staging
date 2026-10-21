# Build with the server/ folder as the context:
#   docker build -f encore-recs/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY encore-recs/encore_recs /app/encore_recs

# Runs as the owner of the music files (the compose file sets PUID:PGID). It only reads a copy of the music server's database; it writes its own
# small database and cache under /data.
USER 1000:1000
EXPOSE 8705
ENTRYPOINT ["python", "-m", "encore_recs"]
