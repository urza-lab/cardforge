from __future__ import annotations

import threading
import time

import pytest
from app.metrics import dashboard_cache
from app.metrics.dashboard_service import DashboardSummary


def _fake_summary() -> DashboardSummary:
    return DashboardSummary(
        collection_distinct_items=0,
        collection_total_quantity=0,
        collection_resolved_count=0,
        list_count=0,
        lists_fully_buildable=0,
        average_coverage_percent=0.0,
        scryfall_sync_status="NOT_STARTED",
        scryfall_card_count=0,
        scryfall_source_updated_at=None,
        mtgjson_sync_status="NOT_STARTED",
        mtgjson_price_count=0,
    )


@pytest.fixture(autouse=True)
def _reset_cache():
    dashboard_cache.clear()
    yield
    dashboard_cache.clear()


def test_first_call_blocks_and_computes_fresh(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}

    def fake(db, *, user_id=1):
        calls["n"] += 1
        return _fake_summary()

    monkeypatch.setattr(dashboard_cache, "get_dashboard_summary", fake)

    result = dashboard_cache.get_dashboard_summary_cached()

    assert calls["n"] == 1
    assert result.is_refreshing is False
    assert result.computed_at is not None
    assert result.refresh_eta_seconds is None


def test_second_call_within_ttl_serves_cached_without_recomputing(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}

    def fake(db, *, user_id=1):
        calls["n"] += 1
        return _fake_summary()

    monkeypatch.setattr(dashboard_cache, "get_dashboard_summary", fake)

    first = dashboard_cache.get_dashboard_summary_cached()
    second = dashboard_cache.get_dashboard_summary_cached()

    assert calls["n"] == 1
    assert second.computed_at == first.computed_at
    assert second.is_refreshing is False


def test_stale_cache_serves_old_data_with_refreshing_flag_then_updates(monkeypatch: pytest.MonkeyPatch):
    """Real bug this test guards against: a naive cache would either block
    every request for the full recomputation or silently serve stale data
    with no indication - user-requested an honest "refreshing, ETA ~Xs"
    signal instead of either.
    """
    calls = {"n": 0}
    release = threading.Event()

    def fake(db, *, user_id=1):
        calls["n"] += 1
        if calls["n"] == 2:
            assert release.wait(timeout=5)  # hold the background refresh open until the test has observed the stale read
        return _fake_summary()

    monkeypatch.setattr(dashboard_cache, "get_dashboard_summary", fake)
    monkeypatch.setattr(dashboard_cache, "CACHE_TTL_SECONDS", 0)

    first = dashboard_cache.get_dashboard_summary_cached()
    assert calls["n"] == 1

    time.sleep(0.05)  # past the (monkeypatched) 0s TTL
    second = dashboard_cache.get_dashboard_summary_cached()

    assert calls["n"] == 2  # background refresh started...
    assert second.is_refreshing is True
    assert second.computed_at == first.computed_at  # ...but the OLD result is what's actually served

    # Restore a normal TTL before polling below - otherwise every poll call
    # (TTL=0) is itself immediately stale and triggers yet another refresh,
    # which is correct cache behavior but would break this test's own
    # "exactly one refresh happened" assertion.
    monkeypatch.setattr(dashboard_cache, "CACHE_TTL_SECONDS", 60)
    release.set()
    deadline = time.time() + 5
    status = second
    while status.is_refreshing and time.time() < deadline:
        time.sleep(0.05)
        status = dashboard_cache.get_dashboard_summary_cached()

    assert status.is_refreshing is False
    assert calls["n"] == 2  # no additional refresh triggered while one was already in flight


def test_concurrent_stale_requests_only_trigger_one_refresh(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}
    release = threading.Event()

    def fake(db, *, user_id=1):
        calls["n"] += 1
        if calls["n"] == 2:
            assert release.wait(timeout=5)
        return _fake_summary()

    monkeypatch.setattr(dashboard_cache, "get_dashboard_summary", fake)
    monkeypatch.setattr(dashboard_cache, "CACHE_TTL_SECONDS", 0)

    dashboard_cache.get_dashboard_summary_cached()
    time.sleep(0.05)

    results = [dashboard_cache.get_dashboard_summary_cached() for _ in range(5)]
    assert all(r.is_refreshing for r in results)
    assert calls["n"] == 2  # 5 concurrent-ish stale reads still only started one background refresh

    release.set()


def test_clear_resets_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dashboard_cache, "get_dashboard_summary", lambda db, *, user_id=1: _fake_summary())
    dashboard_cache.get_dashboard_summary_cached()

    dashboard_cache.clear()

    calls = {"n": 0}

    def fake(db, *, user_id=1):
        calls["n"] += 1
        return _fake_summary()

    monkeypatch.setattr(dashboard_cache, "get_dashboard_summary", fake)
    dashboard_cache.get_dashboard_summary_cached()
    assert calls["n"] == 1  # cleared, so this is a fresh blocking compute again, not a stale-cache read
