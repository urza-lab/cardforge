import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiDelete, apiGet, apiPostJson, ApiError } from "../api/client";
import { useSort } from "../hooks/useSort";
import type { DashboardSummary } from "../types/dashboard";
import type { CardList, ListType } from "../types/lists";

interface CardListRow extends CardList {
  coverage_percent: number | null;
}

export default function Lists() {
  const { t } = useTranslation();
  const [lists, setLists] = useState<CardList[] | null>(null);
  const [coverageByListId, setCoverageByListId] = useState<Record<number, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [listType, setListType] = useState<ListType>("deck");
  const [creating, setCreating] = useState(false);
  const [typeFilter, setTypeFilter] = useState<"all" | ListType>("all");

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);

  function reload() {
    apiGet<CardList[]>("/lists")
      .then((data) => {
        setLists(data);
        setSelected((prev) => {
          const visible = new Set(data.map((l) => l.id));
          const next = new Set([...prev].filter((id) => visible.has(id)));
          return next.size === prev.size ? prev : next;
        });
      })
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : String(err)));
    // Coverage % per list piggybacks on the dashboard's own already-computed
    // buildability numbers (app.metrics.dashboard_service) rather than a
    // second comparison engine call per list here - loaded separately so a
    // slow dashboard computation (real collections with many lists can take
    // several seconds, see CLAUDE.md) doesn't delay the list table itself
    // from rendering; the Coverage column just fills in once it resolves.
    apiGet<DashboardSummary>("/dashboard")
      .then((summary) => {
        const map: Record<number, number> = {};
        for (const lb of summary.list_buildability) map[lb.list_id] = lb.coverage_percent;
        setCoverageByListId(map);
      })
      .catch(() => {
        // Coverage column just stays empty if this fails - not fatal to the page.
      });
  }

  useEffect(reload, []);

  const rows: CardListRow[] = useMemo(
    () =>
      (lists ?? [])
        .filter((l) => typeFilter === "all" || l.list_type === typeFilter)
        .map((l) => ({ ...l, coverage_percent: coverageByListId[l.id] ?? null })),
    [lists, coverageByListId, typeFilter],
  );

  const { sorted, sortKey, direction, toggleSort } = useSort<CardListRow>(rows, "created_at", "desc");

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await apiPostJson<CardList>("/lists", { name: name.trim(), list_type: listType });
      setName("");
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }

  function sortIndicator(key: keyof CardListRow) {
    if (sortKey !== key) return "";
    return direction === "asc" ? " ▲" : " ▼";
  }

  const allSelected = sorted.length > 0 && sorted.every((l) => selected.has(l.id));

  function toggleOne(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(sorted.map((l) => l.id)));
  }

  const selectedRefreshable = sorted.filter((l) => selected.has(l.id) && !!l.source_url);

  async function handleBulkDelete() {
    const targets = sorted.filter((l) => selected.has(l.id));
    if (targets.length === 0) return;
    setBulkBusy(true);
    setBulkError(null);
    setBulkProgress({ done: 0, total: targets.length });
    for (let i = 0; i < targets.length; i++) {
      try {
        await apiDelete(`/lists/${targets[i].id}`);
      } catch (err) {
        setBulkError(err instanceof ApiError ? err.message : String(err));
      }
      setBulkProgress({ done: i + 1, total: targets.length });
    }
    setBulkBusy(false);
    setBulkProgress(null);
    setSelected(new Set());
    reload();
  }

  async function handleBulkRefresh() {
    const targets = selectedRefreshable;
    if (targets.length === 0) return;
    setBulkBusy(true);
    setBulkError(null);
    setBulkProgress({ done: 0, total: targets.length });
    for (let i = 0; i < targets.length; i++) {
      try {
        await apiPostJson(`/lists/${targets[i].id}/refresh`, {});
      } catch (err) {
        setBulkError(err instanceof ApiError ? err.message : String(err));
      }
      setBulkProgress({ done: i + 1, total: targets.length });
    }
    setBulkBusy(false);
    setBulkProgress(null);
    reload();
  }

  return (
    <div>
      <h2>{t("nav.lists")}</h2>
      {error && <div className="cf-alert cf-alert-error">{error}</div>}

      <form className="cf-card" onSubmit={handleCreate}>
        <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10 }}>
          <div style={{ flex: 1 }}>
            <label htmlFor="list-name">{t("listsPage.name")}</label>
            <input
              id="list-name"
              className="cf-input"
              style={{ width: "100%" }}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("listsPage.namePlaceholder")}
            />
          </div>
          <div>
            <label htmlFor="list-type">{t("listsPage.type")}</label>
            <select
              id="list-type"
              className="cf-select"
              value={listType}
              onChange={(e) => setListType(e.target.value as ListType)}
            >
              <option value="deck">{t("listsPage.types.deck")}</option>
              <option value="cube">{t("listsPage.types.cube")}</option>
            </select>
          </div>
          <button type="submit" className="cf-btn cf-btn-primary" disabled={creating || !name.trim()}>
            {t("listsPage.create")}
          </button>
        </div>
      </form>

      <div className="cf-card">
        {!lists && !error && <p>{t("common.loading")}</p>}
        {lists && lists.length === 0 && <p>{t("listsPage.empty")}</p>}
        {lists && lists.length > 0 && (
          <>
            {bulkError && <div className="cf-alert cf-alert-error">{bulkError}</div>}
            <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10 }}>
              <div>
                <label htmlFor="list-type-filter">{t("listsPage.filterType")}</label>
                <select
                  id="list-type-filter"
                  className="cf-select"
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value as "all" | ListType)}
                >
                  <option value="all">{t("listsPage.filterAll")}</option>
                  <option value="deck">{t("listsPage.types.deck")}</option>
                  <option value="cube">{t("listsPage.types.cube")}</option>
                </select>
              </div>
            </div>
            <div className="cf-btn-row" style={{ alignItems: "center", gap: 10 }}>
              <button
                className="cf-btn"
                disabled={selected.size === 0 || bulkBusy}
                onClick={handleBulkDelete}
              >
                {bulkBusy && bulkProgress
                  ? t("listsPage.bulkProgress", { done: bulkProgress.done, total: bulkProgress.total })
                  : t("listsPage.bulkDelete", { count: selected.size })}
              </button>
              <button
                className="cf-btn"
                disabled={selectedRefreshable.length === 0 || bulkBusy}
                onClick={handleBulkRefresh}
              >
                {bulkBusy && bulkProgress
                  ? t("listsPage.bulkProgress", { done: bulkProgress.done, total: bulkProgress.total })
                  : t("listsPage.bulkRefresh", { count: selectedRefreshable.length })}
              </button>
            </div>

            <div className="cf-table-wrap">
              <table className="cf-table">
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleAll}
                        aria-label={t("discoverPage.selectAll")}
                      />
                    </th>
                    <th className="cf-th-sortable" onClick={() => toggleSort("name")}>
                      {t("listsPage.columns.name")}
                      {sortIndicator("name")}
                    </th>
                    <th className="cf-th-sortable" onClick={() => toggleSort("list_type")}>
                      {t("listsPage.columns.type")}
                      {sortIndicator("list_type")}
                    </th>
                    <th className="cf-th-sortable" onClick={() => toggleSort("created_at")}>
                      {t("listsPage.columns.created")}
                      {sortIndicator("created_at")}
                    </th>
                    <th className="cf-th-sortable" onClick={() => toggleSort("coverage_percent")}>
                      {t("listsPage.columns.coverage")}
                      {sortIndicator("coverage_percent")}
                    </th>
                    <th>{t("sourcesPage.columns.status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selected.has(item.id)}
                          onChange={() => toggleOne(item.id)}
                        />
                      </td>
                      <td>
                        <Link to={`/lists/${item.id}`}>{item.name}</Link>
                      </td>
                      <td>{t(`listsPage.types.${item.list_type}`)}</td>
                      <td>{new Date(item.created_at).toLocaleDateString()}</td>
                      <td>{item.coverage_percent !== null ? `${item.coverage_percent.toFixed(0)}%` : "—"}</td>
                      <td>
                        {item.source_url && (
                          <span
                            className={
                              item.refresh_status === "FAILED" || item.refresh_status === "AUTH_REQUIRED"
                                ? "cf-badge cf-badge-error"
                                : item.is_stale
                                  ? "cf-badge cf-badge-warn"
                                  : "cf-badge cf-badge-ok"
                            }
                          >
                            {item.is_stale
                              ? t("listDetailPage.refreshStatus.STALE")
                              : t(`listsImportPage.sourceTypes.${item.source_type}`)}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
