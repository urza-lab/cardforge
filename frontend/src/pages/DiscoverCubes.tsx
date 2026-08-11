import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, apiPostJson, ApiError } from "../api/client";
import type { CubeDiscoverySyncStatusRead, PopularCube } from "../types/cubecobra";
import type { CardList, ListImportPreview, ListImportSummary } from "../types/lists";

const POLL_INTERVAL_MS = 3000;

type ImportState = "idle" | "importing" | "done" | "error";

async function importCube(cube: PopularCube): Promise<{ listId: number } | { error: string }> {
  try {
    const list = await apiPostJson<CardList>("/lists", { name: cube.name, list_type: "cube" });
    const preview = await apiPostJson<ListImportPreview>("/list-imports/preview-url", {
      list_id: list.id,
      url: cube.source_url,
    });
    await apiPostJson<ListImportSummary>(`/list-imports/${preview.id}/confirm`, { skip_bad_rows: true });
    return { listId: list.id };
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
  const [sort, setSort] = useState<"likes" | "cards">("likes");

  const [importState, setImportState] = useState<Record<number, ImportState>>({});
  const [importResult, setImportResult] = useState<Record<number, { listId: number } | { error: string }>>({});

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null);

  const fetchStatus = () => {
    apiGet<CubeDiscoverySyncStatusRead>("/cube-discover/cubes/status")
      .then(setStatus)
      .catch((err: unknown) => setStatusError(err instanceof ApiError ? err.message : String(err)));
  };

  const fetchCubes = () => {
    apiGet<PopularCube[]>(`/cube-discover/cubes?sort=${sort}`)
      .then(setCubes)
      .catch((err: unknown) => setCubesError(err instanceof ApiError ? err.message : String(err)));
  };

  useEffect(fetchStatus, []);
  useEffect(fetchCubes, [sort]);

  useEffect(() => {
    setSelected((prev) => {
      if (!cubes) return prev;
      const visible = new Set(cubes.map((c) => c.id));
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

  async function handleImport(cube: PopularCube) {
    setImportState((s) => ({ ...s, [cube.id]: "importing" }));
    const result = await importCube(cube);
    setImportState((s) => ({ ...s, [cube.id]: "error" in result ? "error" : "done" }));
    setImportResult((r) => ({ ...r, [cube.id]: result }));
  }

  const selectableCubes = (cubes ?? []).filter((c) => importState[c.id] !== "done");
  const allSelectableSelected = selectableCubes.length > 0 && selectableCubes.every((c) => selected.has(c.id));

  function toggleOne(cubeId: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(cubeId)) next.delete(cubeId);
      else next.add(cubeId);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelectableSelected ? new Set() : new Set(selectableCubes.map((c) => c.id)));
  }

  async function handleBulkImport() {
    const targets = (cubes ?? []).filter((c) => selected.has(c.id) && importState[c.id] !== "done");
    if (targets.length === 0) return;

    setBulkRunning(true);
    setBulkProgress({ done: 0, total: targets.length });
    for (let i = 0; i < targets.length; i++) {
      const cube = targets[i];
      setImportState((s) => ({ ...s, [cube.id]: "importing" }));
      const result = await importCube(cube);
      setImportState((s) => ({ ...s, [cube.id]: "error" in result ? "error" : "done" }));
      setImportResult((r) => ({ ...r, [cube.id]: result }));
      setBulkProgress({ done: i + 1, total: targets.length });
    }
    setSelected(new Set());
    setBulkRunning(false);
  }

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
              <div className="cf-stat-value">{status.cube_count}</div>
              <div className="cf-stat-label">{t("discoverCubesPage.cachedCubes")}</div>
            </div>
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
        </div>
      </div>

      <div className="cf-card">
        <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10 }}>
          <div>
            <label htmlFor="dc-sort">{t("discoverPage.sortBy")}</label>
            <select id="dc-sort" className="cf-select" value={sort} onChange={(e) => setSort(e.target.value as "likes" | "cards")}>
              <option value="likes">{t("discoverCubesPage.sortLikes")}</option>
              <option value="cards">{t("discoverCubesPage.sortCards")}</option>
            </select>
          </div>
        </div>

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
                    <th>{t("discoverCubesPage.columns.cards")}</th>
                    <th>{t("discoverPage.columns.likes")}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {cubes.map((cube) => {
                    const state = importState[cube.id] ?? "idle";
                    const result = importResult[cube.id];
                    return (
                      <tr key={cube.id}>
                        <td>
                          <input
                            type="checkbox"
                            disabled={state === "done"}
                            checked={selected.has(cube.id)}
                            onChange={() => toggleOne(cube.id)}
                          />
                        </td>
                        <td>
                          <a href={cube.source_url} target="_blank" rel="noreferrer">
                            {cube.name}
                          </a>
                        </td>
                        <td>{cube.owner_username ?? "—"}</td>
                        <td>{cube.card_count}</td>
                        <td>{cube.like_count.toLocaleString()}</td>
                        <td>
                          {state === "done" && result && "listId" in result ? (
                            <Link className="cf-btn" to={`/lists/${result.listId}`}>
                              {t("discoverPage.viewList")}
                            </Link>
                          ) : state === "error" ? (
                            <span title={result && "error" in result ? result.error : ""} className="cf-badge cf-badge-error">
                              {t("discoverPage.importFailed")}
                            </span>
                          ) : (
                            <button className="cf-btn" disabled={state === "importing"} onClick={() => handleImport(cube)}>
                              {state === "importing" ? t("common.loading") : t("discoverPage.import")}
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
