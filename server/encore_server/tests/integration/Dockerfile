# The test image: the server's own dependencies, ffmpeg (to make and repackage real audio), pytest, and the tests.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY pyproject.toml .
COPY encore_server encore_server
RUN pip install --no-cache-dir -e ".[youtube,dev]"
COPY tests tests
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider", "-m", "integration", "tests/integration"]
