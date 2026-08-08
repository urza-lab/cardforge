# Build context for this Dockerfile is the REPO ROOT (see docker-compose.yml:
# `context: .`, `dockerfile: backend/Dockerfile`), not ./backend — because
# migrations/ lives at the repo root (per the project's top-level layout) but
# needs to end up alongside app/ and alembic.ini inside the image. All COPY
# source paths below are therefore relative to the repo root.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 cardforge && \
    useradd --uid 1000 --gid cardforge --shell /bin/sh --create-home cardforge

WORKDIR /app

FROM base AS build-deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --user -r requirements.txt

FROM base AS runtime
COPY --from=build-deps /root/.local /home/cardforge/.local
ENV PATH=/home/cardforge/.local/bin:$PATH

COPY backend/app ./app
COPY migrations ./migrations
COPY backend/alembic.ini .
COPY backend/scripts ./scripts

RUN mkdir -p /data/secrets /data/scryfall_cache && chown -R cardforge:cardforge /app /data
USER cardforge

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health/live', timeout=3).status==200 else 1)"

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
