import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, apiPostJson, ApiError } from "../api/client";
import type { CardList } from "../types/lists";
import { parseUtcTimestamp } from "../utils/time";

const POLL_INTERVAL_MS = 3000;

export default function Sources() {
  const { t } = useTranslation();
  const [lists, setLists] = useState<CardList[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);

  const reload = useCallback(() => {
    apiGet<CardList[]>("/lists")
      .then(setLists)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  useEffect(reload, [reload]);

  const sourced = (lists ?? []).filter((l) => l.source_url);
  const anyFetching = sourced.some((l) => l.refresh_status === "FETCHING");

  useEffect(() => {
    if (!anyFetching) return;
    const poll = setInterval(reload, POLL_INTERVAL_MS);
    return () => clearInterval(poll);
  }, [anyFetching, reload]);

  async function handleRefresh(listId: number) {
    setRefreshingId(listId);
    setError(null);
    try {
      const updated = await apiPostJson<CardList>(`/lists/${listId}/refresh`, {});
      setLists((prev) => (prev ? prev.map((l) => (l.id === listId ? updated : l)) : prev));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRefreshingId(null);
    }
  }

  function badgeClass(item: CardList) {
    if (item.refresh_status === "CURRENT" && !item.is_stale) return "cf-badge cf-badge-ok";
    if (item.refresh_status === "FAILED" || item.refresh_status === "AUTH_REQUIRED") return "cf-badge cf-badge-error";
    return "cf-badge cf-badge-warn";
  }

  function statusLabel(item: CardList) {
    if (item.is_stale && item.refresh_status === "CURRENT") return t("listDetailPage.refreshStatus.STALE");
    if (item.refresh_status) return t(`listDetailPage.refreshStatus.${item.refresh_status}`);
    return "—";
  }

  return (
    <div>
      <h2>{t("nav.sources")}</h2>
      <div className="cf-card">
        <p style={{ marginTop: 0, color: "var(--cf-muted)" }}>{t("sourcesPage.intro")}</p>

        {error && <div className="cf-alert cf-alert-error">{error}</div>}
        {!lists && !error && <p>{t("common.loading")}</p>}
        {lists && sourced.length === 0 && <p>{t("sourcesPage.empty")}</p>}

        {sourced.length > 0 && (
          <div className="cf-table-wrap">
            <table className="cf-table">
              <thead>
                <tr>
                  <th>{t("listsPage.columns.name")}</th>
                  <th>{t("sourcesPage.columns.provider")}</th>
                  <th>{t("sourcesPage.columns.status")}</th>
                  <th>{t("listDetailPage.lastRefreshed")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sourced.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <Link to={`/lists/${item.id}`}>{item.name}</Link>
                    </td>
                    <td>
                      <a href={item.source_url ?? undefined} target="_blank" rel="noreferrer">
                        {t(`listsImportPage.sourceTypes.${item.source_type}`)}
                      </a>
                    </td>
                    <td>
                      <span className={badgeClass(item)}>{statusLabel(item)}</span>
                    </td>
                    <td>{item.last_refreshed_at ? new Date(parseUtcTimestamp(item.last_refreshed_at)).toLocaleString() : "—"}</td>
                    <td>
                      <button
                        className="cf-btn"
                        disabled={refreshingId === item.id || item.refresh_status === "FETCHING"}
                        onClick={() => handleRefresh(item.id)}
                      >
                        {item.refresh_status === "FETCHING"
                          ? t("listDetailPage.refreshing")
                          : t("listDetailPage.refreshNow")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
