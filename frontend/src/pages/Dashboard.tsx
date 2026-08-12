import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, ApiError } from "../api/client";
import { useSort } from "../hooks/useSort";
import type { DashboardSummary, ListBuildability } from "../types/dashboard";
import type { UserSettings } from "../types/settings";

export default function Dashboard() {
  const { t } = useTranslation();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [grafanaEmbedUrl, setGrafanaEmbedUrl] = useState<string | null>(null);

  const { sorted: sortedBuildability, sortKey, direction, toggleSort } = useSort<ListBuildability>(
    summary?.list_buildability ?? [],
    "coverage_percent",
    "asc",
  );

  function sortIndicator(key: keyof ListBuildability) {
    if (sortKey !== key) return "";
    return direction === "asc" ? " ▲" : " ▼";
  }

  useEffect(() => {
    apiGet<DashboardSummary>("/dashboard")
      .then(setSummary)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : String(err)));
    apiGet<UserSettings>("/settings")
      .then((s) => setGrafanaEmbedUrl(s.grafana_embed_url))
      .catch(() => undefined); // optional feature - a settings fetch failure shouldn't block the rest of the dashboard
  }, []);

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
          <div className="cf-table-wrap" style={{ marginTop: 16 }}>
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
                {sortedBuildability.map((lb) => (
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
        )}
        {summary.list_buildability.length === 0 && <p>{t("dashboardPage.noLists")}</p>}
      </div>

      {summary.top_leverage.length > 0 && (
        <div className="cf-card">
          <h3 style={{ marginTop: 0 }}>{t("dashboardPage.leverage.title")}</h3>
          <p style={{ color: "var(--cf-muted)", marginTop: 0 }}>{t("dashboardPage.leverage.hint")}</p>
          <div className="cf-table-wrap">
            <table className="cf-table">
              <thead>
                <tr>
                  <th>{t("comparisonsPage.columns.name")}</th>
                  <th>{t("dashboardPage.leverage.quantityNeeded")}</th>
                  <th>{t("dashboardPage.leverage.listsNewlyBuildable")}</th>
                  <th>{t("dashboardPage.leverage.coverageGain")}</th>
                </tr>
              </thead>
              <tbody>
                {summary.top_leverage.map((c) => (
                  <tr key={`${c.name}::${c.oracle_id ?? c.scryfall_card_id ?? ""}`}>
                    <td>{c.name}</td>
                    <td>{c.quantity_needed}</td>
                    <td>{c.lists_newly_buildable}</td>
                    <td>+{c.total_coverage_gain}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
