import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, apiPostForm, apiPostJson, ApiError } from "../api/client";
import type { PreconDeck, PreconSyncStatusRead } from "../types/mtgjsonPrecons";
import type { CardList, ListImportPreview, ListImportSummary } from "../types/lists";

const POLL_INTERVAL_MS = 5000;

type ImportState = "idle" | "importing" | "done" | "error";

export default function PreconDecks() {
  const { t } = useTranslation();

  const [status, setStatus] = useState<PreconSyncStatusRead | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const [decks, setDecks] = useState<PreconDeck[] | null>(null);
  const [decksError, setDecksError] = useState<string | null>(null);

  const [importState, setImportState] = useState<Record<number, ImportState>>({});
  const [importResult, setImportResult] = useState<Record<number, { listId: number } | { error: string }>>({});

  const fetchStatus = useCallback(() => {
    apiGet<PreconSyncStatusRead>("/precons/decks/status")
      .then(setStatus)
      .catch((err: unknown) => setStatusError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  const fetchDecks = useCallback(() => {
    apiGet<PreconDeck[]>("/precons/decks")
      .then(setDecks)
      .catch((err: unknown) => setDecksError(err instanceof ApiError ? err.message : String(err)));
  }, []);

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
      const resp = await apiPostJson<PreconSyncStatusRead>("/precons/decks/sync", {});
      setStatus(resp);
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }

  async function handleImport(deck: PreconDeck) {
    setImportState((s) => ({ ...s, [deck.id]: "importing" }));
    try {
      const list = await apiPostJson<CardList>("/lists", { name: deck.name, list_type: "deck" });
      const form = new FormData();
      form.set("source_type", "csv");
      form.set("list_id", String(list.id));
      form.set("file", new File([deck.deck_text], `${deck.file_name}.csv`));
      const preview = await apiPostForm<ListImportPreview>("/list-imports/preview", form);
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
      <h2>{t("nav.precons")}</h2>

      <div className="cf-card">
        <p style={{ marginTop: 0, color: "var(--cf-muted)" }}>{t("preconsPage.intro")}</p>
        {statusError && <div className="cf-alert cf-alert-error">{statusError}</div>}
        {status && (
          <div className="cf-stat-row">
            <div className="cf-stat">
              <span className={syncBadgeClass}>{t(`preconsPage.status.${status.status}`)}</span>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{status.deck_count}</div>
              <div className="cf-stat-label">{t("preconsPage.cachedDecks")}</div>
            </div>
          </div>
        )}
        {status?.status === "FAILED" && status.error_message && (
          <div className="cf-alert cf-alert-error">{status.error_message}</div>
        )}
        {status?.status === "CURRENT" && status.error_message && (
          <div className="cf-alert cf-alert-warn">{status.error_message}</div>
        )}
        <div className="cf-btn-row">
          <button
            className="cf-btn cf-btn-primary"
            disabled={syncing || status?.status === "FETCHING"}
            onClick={handleSync}
          >
            {status?.status === "FETCHING" ? t("preconsPage.syncing") : t("preconsPage.syncNow")}
          </button>
        </div>
      </div>

      <div className="cf-card">
        {decksError && <div className="cf-alert cf-alert-error">{decksError}</div>}
        {!decks && !decksError && <p>{t("common.loading")}</p>}
        {decks && decks.length === 0 && <p>{t("preconsPage.empty")}</p>}

        {decks && decks.length > 0 && (
          <div className="cf-table-wrap">
            <table className="cf-table">
              <thead>
                <tr>
                  <th>{t("preconsPage.columns.name")}</th>
                  <th>{t("preconsPage.columns.commanders")}</th>
                  <th>{t("preconsPage.columns.releaseDate")}</th>
                  <th>{t("preconsPage.columns.cardCount")}</th>
                  <th>{t("preconsPage.columns.coverage")}</th>
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
                      <td>{deck.commander_names.join(", ")}</td>
                      <td>{deck.release_date ?? "—"}</td>
                      <td>{deck.card_count}</td>
                      <td>
                        <span className={deck.is_fully_buildable ? "cf-badge cf-badge-ok" : "cf-badge cf-badge-warn"}>
                          {deck.coverage_percent.toFixed(0)}%
                        </span>
                        {!deck.is_fully_buildable && (
                          <span style={{ marginLeft: 6, color: "var(--cf-muted)" }}>
                            {t("preconsPage.missingCount", { count: deck.missing_count })}
                          </span>
                        )}
                      </td>
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
