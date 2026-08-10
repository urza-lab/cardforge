import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, apiPostJson, ApiError } from "../api/client";
import type { DeckDiscoverySyncStatusRead, PopularDeck } from "../types/discover";
import type { CardList, ListImportPreview, ListImportSummary } from "../types/lists";

const POLL_INTERVAL_MS = 3000;

type ImportState = "idle" | "importing" | "done" | "error";

export default function Discover() {
  const { t } = useTranslation();

  const [status, setStatus] = useState<DeckDiscoverySyncStatusRead | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const [decks, setDecks] = useState<PopularDeck[] | null>(null);
  const [decksError, setDecksError] = useState<string | null>(null);
  const [sort, setSort] = useState<"views" | "likes">("views");
  const [colorFilter, setColorFilter] = useState("");

  const [importState, setImportState] = useState<Record<number, ImportState>>({});
  const [importResult, setImportResult] = useState<Record<number, { listId: number } | { error: string }>>({});

  const fetchStatus = useCallback(() => {
    apiGet<DeckDiscoverySyncStatusRead>("/discover/decks/status")
      .then(setStatus)
      .catch((err: unknown) => setStatusError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  const fetchDecks = useCallback(() => {
    const params = new URLSearchParams({ sort });
    if (colorFilter.trim()) params.set("color_identity", colorFilter.trim().toUpperCase());
    apiGet<PopularDeck[]>(`/discover/decks?${params.toString()}`)
      .then(setDecks)
      .catch((err: unknown) => setDecksError(err instanceof ApiError ? err.message : String(err)));
  }, [sort, colorFilter]);

  useEffect(fetchStatus, [fetchStatus]);
  useEffect(fetchDecks, [fetchDecks]);

  useEffect(() => {
    if (status?.status !== "FETCHING") return;
    const id = setInterval(() => {
      fetchStatus();
      fetchDecks();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [status?.status, fetchStatus, fetchDecks]);

  async function handleSync() {
    setSyncing(true);
    setStatusError(null);
    try {
      const resp = await apiPostJson<DeckDiscoverySyncStatusRead>("/discover/decks/sync", {});
      setStatus(resp);
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }

  async function handleImport(deck: PopularDeck) {
    setImportState((s) => ({ ...s, [deck.id]: "importing" }));
    try {
      const list = await apiPostJson<CardList>("/lists", { name: deck.name, list_type: "deck" });
      const preview = await apiPostJson<ListImportPreview>("/list-imports/preview-url", {
        list_id: list.id,
        url: deck.source_url,
      });
      await apiPostJson<ListImportSummary>(`/list-imports/${preview.id}/confirm`, { skip_bad_rows: true });
      setImportState((s) => ({ ...s, [deck.id]: "done" }));
      setImportResult((r) => ({ ...r, [deck.id]: { listId: list.id } }));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      setImportState((s) => ({ ...s, [deck.id]: "error" }));
      setImportResult((r) => ({ ...r, [deck.id]: { error: message } }));
    }
  }

  const syncBadgeClass =
    status?.status === "CURRENT"
      ? "cf-badge cf-badge-ok"
      : status?.status === "FAILED"
        ? "cf-badge cf-badge-error"
        : "cf-badge cf-badge-warn";

  return (
    <div>
      <h2>{t("nav.discover")}</h2>

      <div className="cf-card">
        <p style={{ marginTop: 0, color: "var(--cf-muted)" }}>{t("discoverPage.intro")}</p>
        {statusError && <div className="cf-alert cf-alert-error">{statusError}</div>}
        {status && (
          <div className="cf-stat-row">
            <div className="cf-stat">
              <span className={syncBadgeClass}>{t(`discoverPage.status.${status.status}`)}</span>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{status.deck_count}</div>
              <div className="cf-stat-label">{t("discoverPage.cachedDecks")}</div>
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
            {status?.status === "FETCHING" ? t("discoverPage.syncing") : t("discoverPage.syncNow")}
          </button>
        </div>
      </div>

      <div className="cf-card">
        <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10 }}>
          <div>
            <label htmlFor="disc-sort">{t("discoverPage.sortBy")}</label>
            <select id="disc-sort" className="cf-select" value={sort} onChange={(e) => setSort(e.target.value as "views" | "likes")}>
              <option value="views">{t("discoverPage.sortViews")}</option>
              <option value="likes">{t("discoverPage.sortLikes")}</option>
            </select>
          </div>
          <div>
            <label htmlFor="disc-colors">{t("discoverPage.colorFilter")}</label>
            <input
              id="disc-colors"
              className="cf-input"
              style={{ width: 100 }}
              value={colorFilter}
              onChange={(e) => setColorFilter(e.target.value)}
              placeholder="e.g. WU"
            />
          </div>
        </div>

        {decksError && <div className="cf-alert cf-alert-error">{decksError}</div>}
        {!decks && !decksError && <p>{t("common.loading")}</p>}
        {decks && decks.length === 0 && <p>{t("discoverPage.empty")}</p>}

        {decks && decks.length > 0 && (
          <div className="cf-table-wrap">
            <table className="cf-table">
              <thead>
                <tr>
                  <th>{t("comparisonsPage.columns.name")}</th>
                  <th>{t("discoverPage.columns.author")}</th>
                  <th>{t("discoverPage.columns.colors")}</th>
                  <th>{t("discoverPage.columns.views")}</th>
                  <th>{t("discoverPage.columns.likes")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {decks.map((deck) => {
                  const state = importState[deck.id] ?? "idle";
                  const result = importResult[deck.id];
                  return (
                    <tr key={deck.id}>
                      <td>
                        <a href={deck.source_url} target="_blank" rel="noreferrer">
                          {deck.name}
                        </a>
                      </td>
                      <td>{deck.author ?? "—"}</td>
                      <td>{deck.color_identity && deck.color_identity.length > 0 ? deck.color_identity.join("") : "—"}</td>
                      <td>{deck.view_count.toLocaleString()}</td>
                      <td>{deck.like_count.toLocaleString()}</td>
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
                          <button className="cf-btn" disabled={state === "importing"} onClick={() => handleImport(deck)}>
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
        )}
      </div>
    </div>
  );
}
