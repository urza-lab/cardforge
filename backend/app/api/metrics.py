from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.metrics.prometheus_exporter import render_metrics

# No /api prefix - prometheus/prometheus.yml scrapes plain /metrics on the
# backend, matching Prometheus's own path convention (not this app's API).
router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)) -> Response:
    return Response(content=render_metrics(db), media_type=CONTENT_TYPE_LATEST)
