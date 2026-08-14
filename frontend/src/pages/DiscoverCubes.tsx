import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, apiPostJson, ApiError } from "../api/client";
import type { CubeDiscoverySyncStatusRead, CubeFullScrapeStatusRead, PopularCube } from "../types/cubecobra";
import { parseUtcTimestamp } from "../utils/time";

const POLL_INTERVAL_MS = 3000;
const FULL_SCRAPE_POLL_INTERVAL_MS = 5000;

function formatDuration(seconds: number): string {
  const totalSeconds = Math.max(0, Math.round(seconds));
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

async function importCube(cubeId: number): Promise<PopularCube | { error: string }> {
  try {
    return await apiPostJson<PopularCube>(`/cube-discover/cubes/${cubeId}/import`, {});
  } catch (err) {
    return { error: err instanceof ApiError ? err.message : String(err) };
  }
}

export default function DiscoverCubes() {
  const { t } = useTranslation();

  const [status, setStatus] = useState<CubeDiscoverySyncStatusRead | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const [cubes, setCubes] = useState<PopularCube[] | null>(null);
  const [cubesError, setCubesError] = useState<string | null>(null);
  const [sort, setSort] = useState<"likes" | "cards" | "decks" | "followers">("likes");
  const [hasDescriptionFilter, setHasDescriptionFilter] = useState<"" | "true" | "false">("");
  const [featuredFilter, setFeaturedFilter] = useState(false);
  const [minFollowers, setMinFollowers] = useState("");
  // Defaults to a real, non-empty floor rather than "no filter" - user-
  // asked directly what good an unplayable cube is, and real data backs
  // that up: 6.6% of the entire real cache has exactly 1 card (see
  // CLAUDE.md). 40 is a deliberately low bar (keeps legitimate small/
  // "battle box" cubes, only excludes the clearly-broken near-empty
  // entries) - still user-editable/clearable to see everything.
  const [minCardCount, setMinCardCount] = useState("40");
  const [maxCardCount, setMaxCardCount] = useState("");
  // Real bug, user-reported (browser out-of-memory / infinite loading): the
  // list endpoint used to return every matching row with no cap - fine at
  // ~1,000-18,000 cached cubes, but the full-catalog scrape grew the cache
  // past 200,000, and rendering that many rows in one unvirtualized table
  // crashed the tab. Server now caps at `limit`; this is a plain browse
  // top-N, not pagination through the whole cache.
  const [limit, setLimit] = useState("100");

  // Only tracks "a request is in flight right now" - the actual outcome
  // (imported_list_id / import_error) lives on the cube itself, returned
  // by the import endpoint and merged back into `cubes`, so it survives a
  // page reload or a later resync instead of resetting to "Import" every
  // time the way purely client-side state did before (user-reported bug).
  const [pending, setPending] = useState<Set<number>>(new Set());

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null);

  const [retryAllRunning, setRetryAllRunning] = useState(false);
  const [retryAllProgress, setRetryAllProgress] = useState<{ done: number; total: number; startedAt: number } | null>(
    null,
  );

  const [fullScrapeStatus, setFullScrapeStatus] = useState<CubeFullScrapeStatusRead | null>(null);
  const [fullScrapeError, setFullScrapeError] = useState<string | null>(null);
  const [fullScrapeStarting, setFullScrapeStarting] = useState(false);
  // Ticks once a second while running so "elapsed"/"avg per cube" count up
  // smoothly instead of only jumping every poll interval - same pattern as
  // the Dashboard's own refresh-countdown disclaimer.
  const [nowTick, setNowTick] = useState(() => Date.now());

  const fetchFullScrapeStatus = () => {
    apiGet<CubeFullScrapeStatusRead>("/cube-discover/cubes/full-scrape/status")
      .then(setFullScrapeStatus)
      .catch(() => {
        // Non-fatal - this section just stays unavailable if it fails.
      });
  };

  useEffect(fetchFullScrapeStatus, []);

  useEffect(() => {
    if (fullScrapeStatus?.status !== "RUNNING") return;
    // Refresh the cube list itself too, not just the scrape's own counters
    // - user-requested live updates directly on this page, so newly found
    // cubes appear in the table below as the scrape progresses, not only
    // once it's fully done.
    const pollId = setInterval(() => {
      fetchFullScrapeStatus();
      fetchCubes();
    }, FULL_SCRAPE_POLL_INTERVAL_MS);
    const tickId = setInterval(() => setNowTick(Date.now()), 1000);
    return () => {
      clearInterval(pollId);
      clearInterval(tickId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullScrapeStatus?.status]);

  async function handleStartFullScrape() {
    setFullScrapeStarting(true);
    setFullScrapeError(null);
    try {
      const resp = await apiPostJson<CubeFullScrapeStatusRead>("/cube-discover/cubes/full-scrape", {});
      setFullScrapeStatus(resp);
    } catch (err) {
      setFullScrapeError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setFullScrapeStarting(false);
    }
  }

  const fullScrapeElapsedSeconds =
    fullScrapeStatus?.started_at && fullScrapeStatus.status === "RUNNING"
      ? (nowTick - parseUtcTimestamp(fullScrapeStatus.started_at)) / 1000
      : null;
  const fullScrapeAvgSecondsPerCube =
    fullScrapeElapsedSeconds !== null && fullScrapeStatus && fullScrapeStatus.cubes_found > 0
      ? fullScrapeElapsedSeconds / fullScrapeStatus.cubes_found
      : null;

  const fetchStatus = () => {
    apiGet<CubeDiscoverySyncStatusRead>("/cube-discover/cubes/status")
      .then(setStatus)
      .catch((err: unknown) => setStatusError(err instanceof ApiError ? err.message : String(err)));
  };

  const fetchCubes = () => {
    const params = new URLSearchParams({ sort });
    if (hasDescriptionFilter) params.set("has_description", hasDescriptionFilter);
    if (featuredFilter) params.set("featured", "true");
    if (minFollowers.trim()) params.set("min_followers", minFollowers.trim());
    if (minCardCount.trim()) params.set("min_card_count", minCardCount.trim());
    if (maxCardCount.trim()) params.set("max_card_count", maxCardCount.trim());
    params.set("limit", limit);
    apiGet<PopularCube[]>(`/cube-discover/cubes?${params.toString()}`)
      .then(setCubes)
      .catch((err: unknown) => setCubesError(err instanceof ApiError ? err.message : String(err)));
  };

  useEffect(fetchStatus, []);
  useEffect(fetchCubes, [sort, hasDescriptionFilter, featuredFilter, minFollowers, minCardCount, maxCardCount, limit]);

  useEffect(() => {
    setSelected((prev) => {
      if (!cubes) return prev;
      const visible = new Set(cubes.filter((c) => !c.imported_list_id).map((c) => c.id));
      const next = new Set([...prev].filter((id) => visible.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [cubes]);

  useEffect(() => {
    if (status?.status !== "FETCHING") return;
    const id = setInterval(() => {
      fetchStatus();
      fetchCubes();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.status]);

  async function handleSync() {
    setSyncing(true);
    setStatusError(null);
    try {
      const resp = await apiPostJson<CubeDiscoverySyncStatusRead>("/cube-discover/cubes/sync", {});
      setStatus(resp);
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }

  function applyResult(result: PopularCube | { error: string }) {
    if ("error" in result) return; // the endpoint itself failed to respond at all (network/5xx) - nothing to merge
    setCubes((prev) => (prev ? prev.map((c) => (c.id === result.id ? result : c)) : prev));
  }

  async function handleImport(cube: PopularCube) {
    setPending((s) => new Set(s).add(cube.id));
    const result = await importCube(cube.id);
    applyResult(result);
    setPending((s) => {
      const next = new Set(s);
      next.delete(cube.id);
      return next;
    });
  }

  const importableCubes = useMemo(() => (cubes ?? []).filter((c) => !c.imported_list_id), [cubes]);
  const failedCubes = useMemo(() => (cubes ?? []).filter((c) => !c.imported_list_id && c.import_error), [cubes]);
  const allSelectableSelected = importableCubes.length > 0 && importableCubes.every((c) => selected.has(c.id));

  function toggleOne(cubeId: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(cubeId)) next.delete(cubeId);
      else next.add(cubeId);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelectableSelected ? new Set() : new Set(importableCubes.map((c) => c.id)));
  }

  async function handleBulkImport() {
    const targets = importableCubes.filter((c) => selected.has(c.id));
    if (targets.length === 0) return;

    setBulkRunning(true);
    setBulkProgress({ done: 0, total: targets.length });
    for (let i = 0; i < targets.length; i++) {
      const cube = targets[i];
      setPending((s) => new Set(s).add(cube.id));
      const result = await importCube(cube.id);
      applyResult(result);
      setPending((s) => {
        const next = new Set(s);
        next.delete(cube.id);
        return next;
      });
      setBulkProgress({ done: i + 1, total: targets.length });
    }
    setSelected(new Set());
    setBulkRunning(false);
  }

  async function handleRetryAll() {
    if (failedCubes.length === 0) return;
    setRetryAllRunning(true);
    setRetryAllProgress({ done: 0, total: failedCubes.length, startedAt: Date.now() });
    for (let i = 0; i < failedCubes.length; i++) {
      const cube = failedCubes[i];
      setPending((s) => new Set(s).add(cube.id));
      const result = await importCube(cube.id);
      applyResult(result);
      setPending((s) => {
        const next = new Set(s);
        next.delete(cube.id);
        return next;
      });
      setRetryAllProgress((prev) => (prev ? { ...prev, done: i + 1 } : prev));
    }
    setRetryAllRunning(false);
    setRetryAllProgress(null);
  }

  const retryAllEtaSeconds = (() => {
    if (!retryAllProgress || retryAllProgress.done === 0) return null;
    const elapsedMs = Date.now() - retryAllProgress.startedAt;
    const perItemMs = elapsedMs / retryAllProgress.done;
    const remaining = retryAllProgress.total - retryAllProgress.done;
    return Math.round((perItemMs * remaining) / 1000);
  })();

  const syncBadgeClass =
    status?.status === "CURRENT"
      ? "cf-badge cf-badge-ok"
      : status?.status === "FAILED"
        ? "cf-badge cf-badge-error"
        : "cf-badge cf-badge-warn";

  return (
    <div>
      <h2>{t("nav.discoverCubes")}</h2>

      <div className="cf-card">
        <p style={{ marginTop: 0, color: "var(--cf-muted)" }}>{t("discoverCubesPage.intro")}</p>
        {statusError && <div className="cf-alert cf-alert-error">{statusError}</div>}
        {status && (
          <div className="cf-stat-row">
            <div className="cf-stat">
              <span className={syncBadgeClass}>{t(`discoverCubesPage.status.${status.status}`)}</span>
            </div>
            <div className="cf-stat">
              {/* The live cube count, not status.cube_count - that field only
                  ever reflects the regular (bounded, popularity-sorted) sync
                  above, so it'd go stale the moment a full scrape (below)
                  adds cubes of its own. */}
              <div className="cf-stat-value">{cubes?.length ?? status.cube_count}</div>
              <div className="cf-stat-label">{t("discoverCubesPage.cachedCubes")}</div>
            </div>
            {failedCubes.length > 0 && (
              <div className="cf-stat">
                <div className="cf-stat-value">{failedCubes.length}</div>
                <div className="cf-stat-label">{t("discoverCubesPage.failedImports")}</div>
              </div>
            )}
          </div>
        )}
        {status?.status === "FAILED" && status.error_message && (
          <div className="cf-alert cf-alert-error">{status.error_message}</div>
        )}
        <div className="cf-btn-row">
          <button
            className="cf-btn cf-btn-primary"
            disabled={syncing || status?.status === "FETCHING"}
            onClick={handleSync}
          >
            {status?.status === "FETCHING" ? t("discoverCubesPage.syncing") : t("discoverCubesPage.syncNow")}
          </button>
          {failedCubes.length > 0 && (
            <button className="cf-btn" disabled={retryAllRunning} onClick={handleRetryAll}>
              {retryAllRunning
                ? t("discoverCubesPage.retryingAll", {
                    done: retryAllProgress?.done ?? 0,
                    total: retryAllProgress?.total ?? 0,
                    eta:
                      retryAllEtaSeconds !== null
                        ? t("discoverCubesPage.etaSeconds", { seconds: retryAllEtaSeconds })
                        : "",
                  })
                : t("discoverCubesPage.retryAllFailed", { count: failedCubes.length })}
            </button>
          )}
        </div>
      </div>

      <div className="cf-card">
        <h3 style={{ marginTop: 0 }}>{t("discoverCubesPage.fullScrape.title")}</h3>
        <p style={{ color: "var(--cf-muted)" }}>{t("discoverCubesPage.fullScrape.description")}</p>
        {fullScrapeError && <div className="cf-alert cf-alert-error">{fullScrapeError}</div>}
        {fullScrapeStatus?.status === "FAILED" && fullScrapeStatus.error_message && (
          <div className="cf-alert cf-alert-error">{fullScrapeStatus.error_message}</div>
        )}
        {fullScrapeStatus && (
          <div className="cf-stat-row">
            <div className="cf-stat">
              <span
                className={
                  fullScrapeStatus.status === "COMPLETED"
                    ? "cf-badge cf-badge-ok"
                    : fullScrapeStatus.status === "FAILED"
                      ? "cf-badge cf-badge-error"
                      : fullScrapeStatus.status === "RUNNING"
                        ? "cf-badge cf-badge-warn"
                        : "cf-badge"
                }
              >
                {t(`discoverCubesPage.fullScrape.status.${fullScrapeStatus.status}`)}
              </span>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{fullScrapeStatus.cubes_found.toLocaleString()}</div>
              <div className="cf-stat-label">{t("discoverCubesPage.fullScrape.cubesFound")}</div>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{fullScrapeStatus.pages_fetched.toLocaleString()}</div>
              <div className="cf-stat-label">{t("discoverCubesPage.fullScrape.pagesFetched")}</div>
            </div>
            {fullScrapeStatus.status === "RUNNING" && fullScrapeElapsedSeconds !== null && (
              <div className="cf-stat">
                <div className="cf-stat-value">{formatDuration(fullScrapeElapsedSeconds)}</div>
                <div className="cf-stat-label">
                  {fullScrapeAvgSecondsPerCube !== null
                    ? t("discoverCubesPage.fullScrape.avgPerCube", { seconds: fullScrapeAvgSecondsPerCube.toFixed(1) })
                    : t("discoverCubesPage.fullScrape.elapsedLabel")}
                </div>
              </div>
            )}
          </div>
        )}
        <div className="cf-btn-row">
          <button
            className="cf-btn cf-btn-primary"
            disabled={fullScrapeStarting || fullScrapeStatus?.status === "RUNNING"}
            onClick={handleStartFullScrape}
          >
            {fullScrapeStatus?.status === "RUNNING"
              ? t("discoverCubesPage.fullScrape.status.RUNNING")
              : t("discoverCubesPage.fullScrape.start")}
          </button>
        </div>
      </div>

      <div className="cf-card">
        <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10 }}>
          <div>
            <label htmlFor="dc-sort">{t("discoverPage.sortBy")}</label>
            <select
              id="dc-sort"
              className="cf-select"
              value={sort}
              onChange={(e) => setSort(e.target.value as "likes" | "cards" | "decks" | "followers")}
            >
              <option value="likes">{t("discoverCubesPage.sortLikes")}</option>
              <option value="cards">{t("discoverCubesPage.sortCards")}</option>
              <option value="decks">{t("discoverCubesPage.sortDecks")}</option>
              <option value="followers">{t("discoverCubesPage.sortFollowers")}</option>
            </select>
          </div>
          <div>
            <label htmlFor="dc-has-description">{t("discoverCubesPage.hasDescriptionFilter")}</label>
            <select
              id="dc-has-description"
              className="cf-select"
              value={hasDescriptionFilter}
              onChange={(e) => setHasDescriptionFilter(e.target.value as "" | "true" | "false")}
            >
              <option value="">{t("discoverCubesPage.hasDescriptionAny")}</option>
              <option value="true">{t("discoverCubesPage.hasDescriptionYes")}</option>
              <option value="false">{t("discoverCubesPage.hasDescriptionNo")}</option>
            </select>
          </div>
          <div>
            <label htmlFor="dc-min-followers">{t("discoverCubesPage.minFollowers")}</label>
            <input
              id="dc-min-followers"
              className="cf-input"
              style={{ width: 100 }}
              type="number"
              min={0}
              value={minFollowers}
              onChange={(e) => setMinFollowers(e.target.value)}
              placeholder={t("discoverCubesPage.minFollowersAny")}
            />
          </div>
          <div>
            <label htmlFor="dc-min-cards">{t("discoverCubesPage.minCardCount")}</label>
            <input
              id="dc-min-cards"
              className="cf-input"
              style={{ width: 100 }}
              type="number"
              min={0}
              value={minCardCount}
              onChange={(e) => setMinCardCount(e.target.value)}
              placeholder={t("discoverCubesPage.cardCountAny")}
            />
          </div>
          <div>
            <label htmlFor="dc-max-cards">{t("discoverCubesPage.maxCardCount")}</label>
            <input
              id="dc-max-cards"
              className="cf-input"
              style={{ width: 100 }}
              type="number"
              min={0}
              value={maxCardCount}
              onChange={(e) => setMaxCardCount(e.target.value)}
              placeholder={t("discoverCubesPage.cardCountAny")}
            />
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: 6, paddingBottom: 8 }}>
            <input type="checkbox" checked={featuredFilter} onChange={(e) => setFeaturedFilter(e.target.checked)} />
            {t("discoverCubesPage.featuredFilter")}
          </label>
          <div>
            <label htmlFor="dc-limit">{t("discoverCubesPage.limit")}</label>
            <select id="dc-limit" className="cf-select" value={limit} onChange={(e) => setLimit(e.target.value)}>
              <option value="50">50</option>
              <option value="100">100</option>
              <option value="200">200</option>
              <option value="500">500</option>
              <option value="1000">1000</option>
            </select>
          </div>
        </div>
        <p style={{ fontSize: 12, color: "var(--cf-muted)" }}>{t("discoverCubesPage.minCardCountHint")}</p>
        <p style={{ fontSize: 12, color: "var(--cf-muted)" }}>{t("discoverCubesPage.limitHint")}</p>

        {cubesError && <div className="cf-alert cf-alert-error">{cubesError}</div>}
        {!cubes && !cubesError && <p>{t("common.loading")}</p>}
        {cubes && cubes.length === 0 && <p>{t("discoverCubesPage.empty")}</p>}

        {cubes && cubes.length > 0 && (
          <>
            <div className="cf-btn-row" style={{ alignItems: "center", gap: 10 }}>
              <button
                className="cf-btn cf-btn-primary"
                disabled={selected.size === 0 || bulkRunning}
                onClick={handleBulkImport}
              >
                {bulkRunning
                  ? t("discoverPage.bulkImporting", { done: bulkProgress?.done ?? 0, total: bulkProgress?.total ?? 0 })
                  : t("discoverPage.bulkImport", { count: selected.size })}
              </button>
            </div>

            <div className="cf-table-wrap">
              <table className="cf-table">
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        checked={allSelectableSelected}
                        onChange={toggleAll}
                        aria-label={t("discoverPage.selectAll")}
                      />
                    </th>
                    <th>{t("comparisonsPage.columns.name")}</th>
                    <th>{t("discoverCubesPage.columns.owner")}</th>
                    <th>{t("discoverCubesPage.columns.followers")}</th>
                    <th>{t("discoverCubesPage.columns.cards")}</th>
                    <th>{t("discoverPage.columns.likes")}</th>
                    <th>{t("discoverCubesPage.columns.decks")}</th>
                    <th>{t("discoverCubesPage.columns.cubeUpdated")}</th>
                    <th>{t("discoverCubesPage.columns.lastUpdated")}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {cubes.map((cube) => {
                    const isPending = pending.has(cube.id);
                    return (
                      <tr key={cube.id}>
                        <td>
                          <input
                            type="checkbox"
                            disabled={!!cube.imported_list_id}
                            checked={selected.has(cube.id)}
                            onChange={() => toggleOne(cube.id)}
                          />
                        </td>
                        <td>
                          <a
                            href={cube.source_url}
                            target="_blank"
                            rel="noreferrer"
                            title={cube.description ?? undefined}
                          >
                            {cube.name}
                          </a>
                          {cube.featured && (
                            <span className="cf-badge cf-badge-ok" style={{ marginLeft: 6 }}>
                              {t("discoverCubesPage.featuredBadge")}
                            </span>
                          )}
                        </td>
                        <td>{cube.owner_username ?? "—"}</td>
                        <td>{cube.owner_follower_count !== null ? cube.owner_follower_count.toLocaleString() : "—"}</td>
                        <td>{cube.card_count}</td>
                        <td>{cube.like_count.toLocaleString()}</td>
                        <td>{cube.num_decks !== null ? cube.num_decks.toLocaleString() : "—"}</td>
                        <td>
                          {cube.date_last_updated ? new Date(parseUtcTimestamp(cube.date_last_updated)).toLocaleDateString() : "—"}
                        </td>
                        <td>
                          {cube.import_attempted_at ? new Date(parseUtcTimestamp(cube.import_attempted_at)).toLocaleString() : "—"}
                        </td>
                        <td>
                          {cube.imported_list_id ? (
                            <Link className="cf-btn" to={`/lists/${cube.imported_list_id}`}>
                              {t("discoverPage.viewList")}
                            </Link>
                          ) : cube.import_error ? (
                            <span title={cube.import_error} className="cf-badge cf-badge-error">
                              {t("discoverPage.importFailed")}
                            </span>
                          ) : null}
                          {!cube.imported_list_id && (
                            <button
                              className="cf-btn"
                              style={cube.import_error ? { marginLeft: 6 } : undefined}
                              disabled={isPending}
                              onClick={() => handleImport(cube)}
                            >
                              {isPending
                                ? t("common.loading")
                                : cube.import_error
                                  ? t("discoverCubesPage.retry")
                                  : t("discoverPage.import")}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
