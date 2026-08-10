from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.collections import router as collections_router
from app.api.comparisons import router as comparisons_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.list_imports import router as list_imports_router
from app.api.lists import router as lists_router
from app.api.scryfall import router as scryfall_router
from app.api.settings import router as settings_router
from app.api.shopping_list import router as shopping_list_router
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.logging import configure_logging
from app.services import scryfall_service

configure_logging()
settings = get_settings()
log = logging.getLogger("cardforge.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db = get_sessionmaker()()
    try:
        scryfall_service.maybe_auto_trigger_sync(db)
    except Exception:  # noqa: BLE001 - startup must never crash the app over this
        log.exception("failed to check/trigger Scryfall auto-sync at startup")
    finally:
        db.close()
    yield


app = FastAPI(
    title="CardForge — Deck & Cube Finder API",
    version="0.1.0",
    description="Deterministic, non-AI backend for comparing a Magic: The Gathering "
    "collection against Commander decklists and cubes.",
    lifespan=lifespan,
)

# CORS is only relevant for the dev setup (Vite dev server on a different origin).
# In production the frontend container proxies /api same-origin, so CORS is not needed there.
if settings.environment == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health_router)
app.include_router(collections_router)
app.include_router(imports_router)
app.include_router(scryfall_router)
app.include_router(comparisons_router)
app.include_router(settings_router)
app.include_router(lists_router)
app.include_router(list_imports_router)
app.include_router(shopping_list_router)


@app.get("/api")
def root() -> dict:
    return {"name": "CardForge", "status": "ok"}
