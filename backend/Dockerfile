FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 cardforge && \
    useradd --uid 1000 --gid cardforge --shell /bin/sh --create-home cardforge

WORKDIR /app

FROM base AS build-deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --user -r requirements.txt

FROM base AS runtime
COPY --from=build-deps --chown=cardforge:cardforge /root/.local /home/cardforge/.local
ENV PATH=/home/cardforge/.local/bin:$PATH

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
COPY pyproject.toml .
COPY scripts ./scripts

# Set explicitly at build time rather than relying on the executable bit
# surviving git/tar/host-filesystem round-trips (Windows checkouts in
# particular can lose it, since NTFS has no Unix executable bit) -- this
# guarantees entrypoint.sh is runnable regardless of how it got here.
RUN chmod +x scripts/entrypoint.sh scripts/init_secrets.py scripts/wait_for_postgres.py

RUN mkdir -p /data/secrets /data/scryfall_cache && chown -R cardforge:cardforge /app /data
USER cardforge

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health/live', timeout=3).status==200 else 1)"

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]