import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, ApiError } from "../api/client";
import { ROW_LIMIT_OPTIONS, type RowLimit, useLimited, useRowLimit } from "../hooks/useRowLimit";
import { useSort } from "../hooks/useSort";
import type { DashboardSummary, LeverageCandidate, ListBuildability } from "../types/dashboard";
import type { UserSettings } from "../types/settings";
import { parseUtcTimestamp } from "../utils/time";

interface LeverageRow extends LeverageCandidate {
  // Parsed once for numeric sorting/filtering - the API field itself stays
  // a string (Decimal, see types/dashboard.ts) so it round-trips exactly.
  total_price_num: number | null;
}

export default function Dashboard() {
  const { t } = useTranslation();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [grafanaEmbedUrl, setGrafanaEmbedUrl] = useState<string | null>(null);

  const [minListsNewlyBuildable, setMinListsNewlyBuildable] = useState(0);
  const [maxPrice, setMaxPrice] = useState("");

  const { sorted: sortedBuildability, sortKey, direction, toggleSort } = useSort<ListBuildability>(
    summary?.list_buildability ?? [],
    "coverage_percent",
    "asc",
  );

  function sortIndicator(key: keyof ListBuildability) {
    if (sortKey !== key) return "";
    return direction === "asc" ? " ▲" : " ▼";
  }

  const leverageRows: LeverageRow[] = useMemo(
    () =>
      (summary?.top_leverage ?? []).map((c) => ({
        ...c,
        total_price_num: c.total_price !== null ? Number(c.total_price) : null,
      })),
    [summary],
  );

  const filteredLeverage = useMemo(() => {
    const maxPriceNum = maxPrice.trim() ? Number(maxPrice) : null;
    return leverageRows.filter((c) => {
      if (c.lists_newly_buildable < minListsNewlyBuildable) return false;
      if (maxPriceNum !== null && (c.total_price_num === null || c.total_price_num > maxPriceNum)) return false;
      return true;
    });
  }, [leverageRows, minListsNewlyBuildable, maxPrice]);

  const {
    sorted: sortedLeverage,
    sortKey: leverageSortKey,
    direction: leverageDirection,
    toggleSort: toggleLeverageSort,
  } = useSort<LeverageRow>(filteredLeverage, "lists_newly_buildable", "desc");

  function leverageSortIndicator(key: keyof LeverageRow) {
    if (leverageSortKey !== key) return "";
    return leverageDirection === "asc" ? " ▲" : " ▼";
  }

  const leverageRowLimit = useRowLimit(25);
  const visibleLeverage = useLimited(sortedLeverage, leverageRowLimit.limit);
  const buildabilityRowLimit = useRowLimit(25);
  const visibleBuildability = useLimited(sortedBuildability, buildabilityRowLimit.limit);

  useEffect(() => {
    apiGet<DashboardSummary>("/dashboard")
      .then(setSummary)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : String(err)));
    apiGet<UserSettings>("/settings")
      .then((s) => setGrafanaEmbedUrl(s.grafana_embed_url))
      .catch(() => undefined); // optional feature - a settings fetch failure shouldn't block the rest of the dashboard
  }, []);

  // The backend serves a short-lived cache (see app.metrics.dashboard_cache)
  // and reports is_refreshing/refresh_eta_seconds while a background refresh
  // is in flight. Poll while that's true so the page picks up the fresh
  // result as soon as it lands, instead of requiring a manual reload.
  useEffect(() => {
    if (!summary?.is_refreshing) return;
    const id = setInterval(() => {
      apiGet<DashboardSummary>("/dashboard")
        .then(setSummary)
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(id);
  }, [summary?.is_refreshing]);

  // The poll above only re-syncs every 2s, which would make the ETA visibly
  // jump instead of count down. Anchor the server's ETA + the moment we
  // received it, then tick a local display value down every second in
  // between polls for a smooth countdown.
  const [etaAnchor, setEtaAnchor] = useState<{ eta: number; receivedAt: number } | null>(null);
  const [displayEta, setDisplayEta] = useState<number | null>(null);

  useEffect(() => {
    if (summary?.is_refreshing && summary.refresh_eta_seconds !== null) {
      setEtaAnchor({ eta: summary.refresh_eta_seconds, receivedAt: Date.now() });
    } else {
      setEtaAnchor(null);
      setDisplayEta(null);
    }
  }, [summary?.is_refreshing, summary?.refresh_eta_seconds]);

  useEffect(() => {
    if (!etaAnchor) return;
    const tick = () => {
      const elapsed = (Date.now() - etaAnchor.receivedAt) / 1000;
      setDisplayEta(Math.max(Math.ceil(etaAnchor.eta - elapsed), 0));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [etaAnchor]);

  function syncBadgeClass(status: string) {
    if (status === "CURRENT") return "cf-badge cf-badge-ok";
    if (status === "FAILED") return "cf-badge cf-badge-error";
    return "cf-badge cf-badge-warn";
  }

  if (error) {
    return (
      <div>
        <h2>{t("nav.dashboard")}</h2>
        <div className="cf-alert cf-alert-error">{error}</div>
      </div>
    );
  }

  if (!summary) {
    return (
      <div>
        <h2>{t("nav.dashboard")}</h2>
        <p>{t("common.loading")}</p>
      </div>
    );
  }

  return (
    <div>
      <h2>{t("nav.dashboard")}</h2>

      {(summary.computed_at || summary.is_refreshing) && (
        <p style={{ color: "var(--cf-muted)", marginTop: -8 }}>
          {summary.computed_at &&
            t("dashboardPage.cache.asOf", { time: new Date(parseUtcTimestamp(summary.computed_at)).toLocaleTimeString() })}
          {summary.is_refreshing && (
            <>
              {summary.computed_at ? " · " : ""}
              {displayEta !== null
                ? t("dashboardPage.cache.refreshingEta", { seconds: displayEta })
                : t("dashboardPage.cache.refreshing")}
            </>
          )}
        </p>
      )}

      <div className="cf-card">
        <h3 style={{ marginTop: 0 }}>{t("dashboardPage.collection")}</h3>
        <div className="cf-stat-row">
          <div className="cf-stat">
            <div className="cf-stat-value">{summary.collection_distinct_items}</div>
            <div className="cf-stat-label">{t("collection.distinctEntries")}</div>
          </div>
          <div className="cf-stat">
            <div className="cf-stat-value">{summary.collection_total_quantity}</div>
            <div className="cf-stat-label">{t("collection.totalCards")}</div>
          </div>
          <div className="cf-stat">
            <div className="cf-stat-value">{summary.collection_resolved_count}</div>
            <div className="cf-stat-label">{t("dashboardPage.resolvedCount")}</div>
          </div>
        </div>
      </div>

      <div className="cf-card">
        <h3 style={{ marginTop: 0 }}>{t("dashboardPage.grafana.title")}</h3>
        {grafanaEmbedUrl ? (
          <iframe
            src={grafanaEmbedUrl}
            title={t("dashboardPage.grafana.title")}
            style={{ width: "100%", height: 480, border: "none", borderRadius: 6 }}
          />
        ) : (
          <p style={{ color: "var(--cf-muted)", marginTop: 0 }}>
            {t("dashboardPage.grafana.notConfigured")}{" "}
            <Link to="/settings">{t("nav.settings")}</Link>.
          </p>
        )}
      </div>

      {summary.top_leverage.length > 0 && (
        <div className="cf-card">
          <h3 style={{ marginTop: 0 }}>{t("dashboardPage.leverage.title")}</h3>
          <p style={{ color: "var(--cf-muted)", marginTop: 0 }}>{t("dashboardPage.leverage.hint")}</p>

          <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10 }}>
            <div>
              <label htmlFor="leverage-min-lists">{t("dashboardPage.leverage.filterMinLists")}</label>
              <select
                id="leverage-min-lists"
                className="cf-select"
                value={minListsNewlyBuildable}
                onChange={(e) => setMinListsNewlyBuildable(Number(e.target.value))}
              >
                <option value={0}>{t("dashboardPage.leverage.filterMinListsAny")}</option>
                <option value={1}>{t("dashboardPage.leverage.filterMinListsAtLeast", { count: 1 })}</option>
                <option value={2}>{t("dashboardPage.leverage.filterMinListsAtLeast", { count: 2 })}</option>
                <option value={3}>{t("dashboardPage.leverage.filterMinListsAtLeast", { count: 3 })}</option>
              </select>
            </div>
            <div>
              <label htmlFor="leverage-max-price">{t("dashboardPage.leverage.filterMaxPrice")}</label>
              <input
                id="leverage-max-price"
                className="cf-input"
                style={{ width: 100 }}
                type="number"
                min={0}
                step="0.01"
                value={maxPrice}
                onChange={(e) => setMaxPrice(e.target.value)}
                placeholder={t("dashboardPage.leverage.filterMaxPriceAny")}
              />
            </div>
            <div>
              <label htmlFor="leverage-row-limit">{t("dashboardPage.rowLimit.label")}</label>
              <select
                id="leverage-row-limit"
                className="cf-select"
                value={leverageRowLimit.limit}
                onChange={(e) => leverageRowLimit.setLimit((e.target.value === "all" ? "all" : Number(e.target.value)) as RowLimit)}
              >
                {ROW_LIMIT_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {t("dashboardPage.rowLimit.first", { count: n })}
                  </option>
                ))}
                <option value="all">{t("dashboardPage.rowLimit.all")}</option>
              </select>
            </div>
            <div style={{ color: "var(--cf-muted)", paddingBottom: 8 }}>
              {t("dashboardPage.leverage.filterCount", { shown: visibleLeverage.length, total: leverageRows.length })}
            </div>
          </div>

          <div className="cf-table-wrap">
            <table className="cf-table">
              <thead>
                <tr>
                  <th>{t("comparisonsPage.columns.name")}</th>
                  <th className="cf-th-sortable" onClick={() => toggleLeverageSort("quantity_needed")}>
                    {t("dashboardPage.leverage.quantityNeeded")}
                    {leverageSortIndicator("quantity_needed")}
                  </th>
                  <th className="cf-th-sortable" onClick={() => toggleLeverageSort("lists_newly_buildable")}>
                    {t("dashboardPage.leverage.listsNewlyBuildable")}
                    {leverageSortIndicator("lists_newly_buildable")}
                  </th>
                  <th className="cf-th-sortable" onClick={() => toggleLeverageSort("total_coverage_gain")}>
                    {t("dashboardPage.leverage.coverageGain")}
                    {leverageSortIndicator("total_coverage_gain")}
                  </th>
                  <th className="cf-th-sortable" onClick={() => toggleLeverageSort("total_price_num")}>
                    {t("dashboardPage.leverage.totalPrice")}
                    {leverageSortIndicator("total_price_num")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleLeverage.map((c) => (
                  <tr key={`${c.name}::${c.oracle_id ?? c.scryfall_card_id ?? ""}`}>
                    <td>{c.name}</td>
                    <td>{c.quantity_needed}</td>
                    <td>{c.lists_newly_buildable}</td>
                    <td>+{c.total_coverage_gain}%</td>
                    <td>{c.total_price !== null ? `${Number(c.total_price).toFixed(2)} ${c.currency}` : "—"}</td>
                  </tr>
                ))}
                {sortedLeverage.length === 0 && (
                  <tr>
                    <td colSpan={5} style={{ color: "var(--cf-muted)" }}>
                      {t("dashboardPage.leverage.filterEmpty")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="cf-card">
        <h3 style={{ marginTop: 0 }}>{t("dashboardPage.lists")}</h3>
        <div className="cf-stat-row">
          <div className="cf-stat">
            <div className="cf-stat-value">{summary.list_count}</div>
            <div className="cf-stat-label">{t("dashboardPage.listCount")}</div>
          </div>
          <div className="cf-stat">
            <div className="cf-stat-value">{summary.lists_fully_buildable}</div>
            <div className="cf-stat-label">{t("dashboardPage.fullyBuildable")}</div>
          </div>
          <div className="cf-stat">
            <div className="cf-stat-value">{summary.average_coverage_percent}%</div>
            <div className="cf-stat-label">{t("dashboardPage.averageCoverage")}</div>
          </div>
        </div>

        {summary.list_buildability.length > 0 && (
          <>
            <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10, marginTop: 12 }}>
              <div>
                <label htmlFor="buildability-row-limit">{t("dashboardPage.rowLimit.label")}</label>
                <select
                  id="buildability-row-limit"
                  className="cf-select"
                  value={buildabilityRowLimit.limit}
                  onChange={(e) =>
                    buildabilityRowLimit.setLimit((e.target.value === "all" ? "all" : Number(e.target.value)) as RowLimit)
                  }
                >
                  {ROW_LIMIT_OPTIONS.map((n) => (
                    <option key={n} value={n}>
                      {t("dashboardPage.rowLimit.first", { count: n })}
                    </option>
                  ))}
                  <option value="all">{t("dashboardPage.rowLimit.all")}</option>
                </select>
              </div>
              <div style={{ color: "var(--cf-muted)", paddingBottom: 8 }}>
                {t("dashboardPage.leverage.filterCount", {
                  shown: visibleBuildability.length,
                  total: summary.list_buildability.length,
                })}
              </div>
            </div>

            <div className="cf-table-wrap" style={{ marginTop: 8 }}>
              <table className="cf-table">
                <thead>
                  <tr>
                    <th className="cf-th-sortable" onClick={() => toggleSort("name")}>
                      {t("listsPage.columns.name")}
                      {sortIndicator("name")}
                    </th>
                    <th className="cf-th-sortable" onClick={() => toggleSort("list_type")}>
                      {t("listsPage.columns.type")}
                      {sortIndicator("list_type")}
                    </th>
                    <th className="cf-th-sortable" onClick={() => toggleSort("coverage_percent")}>
                      {t("comparisonsPage.coverage")}
                      {sortIndicator("coverage_percent")}
                    </th>
                    <th className="cf-th-sortable" onClick={() => toggleSort("is_fully_buildable")}>
                      {t("dashboardPage.buildable")}
                      {sortIndicator("is_fully_buildable")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visibleBuildability.map((lb) => (
                    <tr key={lb.list_id}>
                      <td>
                        <Link to={`/lists/${lb.list_id}`}>{lb.name}</Link>
                      </td>
                      <td>{t(`listsPage.types.${lb.list_type}`)}</td>
                      <td>{lb.coverage_percent}%</td>
                      <td>
                        <span className={lb.is_fully_buildable ? "cf-badge cf-badge-ok" : "cf-badge cf-badge-warn"}>
                          {lb.is_fully_buildable ? t("common.yes") : t("common.no")}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
        {summary.list_buildability.length === 0 && <p>{t("dashboardPage.noLists")}</p>}
      </div>

      <div className="cf-card">
        <h3 style={{ marginTop: 0 }}>{t("dashboardPage.sources")}</h3>
        <div className="cf-stat-row">
          <div className="cf-stat">
            <span className={syncBadgeClass(summary.scryfall_sync_status)}>
              {t("health.scryfall.title")}: {t(`health.scryfall.status.${summary.scryfall_sync_status}`, summary.scryfall_sync_status)}
            </span>
            <div className="cf-stat-label">{summary.scryfall_card_count.toLocaleString()} {t("health.scryfall.cardCount")}</div>
          </div>
          <div className="cf-stat">
            <span className={syncBadgeClass(summary.mtgjson_sync_status)}>
              {t("pricesPage.mtgjson.title")}: {t(`pricesPage.mtgjson.status.${summary.mtgjson_sync_status}`, summary.mtgjson_sync_status)}
            </span>
            <div className="cf-stat-label">{summary.mtgjson_price_count.toLocaleString()} {t("pricesPage.mtgjson.priceCount")}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
