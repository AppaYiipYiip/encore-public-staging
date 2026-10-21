# Build with the server/ folder as the context (the account tool lives in reference/):
#   docker build -f encore-people/Dockerfile ..
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY encore-people/encore_people /app/encore_people
# The proven account tool (folder + library + account with only its own library and the shared one), docs/26.
COPY reference/encore_user.py /app/encore_user.py

# Runs as the owner of the music files (the compose file sets PUID:PGID); it makes each invited person's folder.
USER 1000:1000
EXPOSE 8702
ENTRYPOINT ["python", "-m", "encore_people"]
