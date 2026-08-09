from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.collections import router as collections_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

app = FastAPI(
    title="CardForge — Deck & Cube Finder API",
    version="0.1.0",
    description="Deterministic, non-AI backend for comparing a Magic: The Gathering "
    "collection against Commander decklists and cubes.",
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


@app.get("/api")
def root() -> dict:
    return {"name": "CardForge", "status": "ok"}
