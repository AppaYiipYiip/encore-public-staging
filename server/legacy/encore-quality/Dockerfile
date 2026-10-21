# Build with the server/ folder as the context:
#   docker build -f encore-quality/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY encore-quality/encore_quality /app/encore_quality

# Runs as the owner of the music files (the compose file sets PUID:PGID). It writes only inside the music folder's .encore folders,
# its own database under /data and Soularr's settings under /soularr.
USER 1000:1000
EXPOSE 8704
ENTRYPOINT ["python", "-m", "encore_quality"]
