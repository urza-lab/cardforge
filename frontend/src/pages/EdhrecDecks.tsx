import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, apiPostForm, apiPostJson, ApiError } from "../api/client";
import type { EdhrecSyncStatusRead, SynthesizedDeck } from "../types/edhrec";
import type { CardList, ListImportPreview, ListImportSummary } from "../types/lists";

const POLL_INTERVAL_MS = 5000;

type ImportState = "idle" | "importing" | "done" | "error";

export default function EdhrecDecks() {
  const { t } = useTranslation();

  const [status, setStatus] = useState<EdhrecSyncStatusRead | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const [decks, setDecks] = useState<SynthesizedDeck[] | null>(null);
  const [decksError, setDecksError] = useState<string | null>(null);
  const [sort, setSort] = useState<"num_decks" | "rank">("num_decks");
  const [colorFilter, setColorFilter] = useState("");

  const [importState, setImportState] = useState<Record<number, ImportState>>({});
  const [importResult, setImportResult] = useState<Record<number, { listId: number } | { error: string }>>({});

  const fetchStatus = useCallback(() => {
    apiGet<EdhrecSyncStatusRead>("/edhrec/decks/status")
      .then(setStatus)
      .catch((err: unknown) => setStatusError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  const fetchDecks = useCallback(() => {
    const params = new URLSearchParams({ sort });
    if (colorFilter.trim()) params.set("color_identity", colorFilter.trim().toUpperCase());
    apiGet<SynthesizedDeck[]>(`/edhrec/decks?${params.toString()}`)
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
      const resp = await apiPostJson<EdhrecSyncStatusRead>("/edhrec/decks/sync", {});
      setStatus(resp);
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }

  async function handleImport(deck: SynthesizedDeck) {
    setImportState((s) => ({ ...s, [deck.id]: "importing" }));
    try {
      const list = await apiPostJson<CardList>("/lists", { name: deck.commander_name, list_type: "deck" });
      const form = new FormData();
      form.set("source_type", "text");
      form.set("list_id", String(list.id));
      form.set("file", new File([deck.deck_text], `${deck.commander_slug}.txt`));
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
      <h2>{t("nav.edhrec")}</h2>

      <div className="cf-card">
        <p style={{ marginTop: 0, color: "var(--cf-muted)" }}>{t("edhrecPage.intro")}</p>
        <div className="cf-alert cf-alert-warn">{t("edhrecPage.disclaimer")}</div>
        {statusError && <div className="cf-alert cf-alert-error">{statusError}</div>}
        {status && (
          <div className="cf-stat-row">
            <div className="cf-stat">
              <span className={syncBadgeClass}>{t(`edhrecPage.status.${status.status}`)}</span>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{status.deck_count}</div>
              <div className="cf-stat-label">{t("edhrecPage.cachedDecks")}</div>
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
            {status?.status === "FETCHING" ? t("edhrecPage.syncing") : t("edhrecPage.syncNow")}
          </button>
        </div>
      </div>

      <div className="cf-card">
        <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10 }}>
          <div>
            <label htmlFor="edhrec-sort">{t("edhrecPage.sortBy")}</label>
            <select
              id="edhrec-sort"
              className="cf-select"
              value={sort}
              onChange={(e) => setSort(e.target.value as "num_decks" | "rank")}
            >
              <option value="num_decks">{t("edhrecPage.sortPopularity")}</option>
              <option value="rank">{t("edhrecPage.sortRank")}</option>
            </select>
          </div>
          <div>
            <label htmlFor="edhrec-colors">{t("edhrecPage.colorFilter")}</label>
            <input
              id="edhrec-colors"
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
        {decks && decks.length === 0 && <p>{t("edhrecPage.empty")}</p>}

        {decks && decks.length > 0 && (
          <div className="cf-table-wrap">
            <table className="cf-table">
              <thead>
                <tr>
                  <th>{t("edhrecPage.columns.commander")}</th>
                  <th>{t("discoverPage.columns.colors")}</th>
                  <th>{t("edhrecPage.columns.numDecks")}</th>
                  <th>{t("edhrecPage.columns.cardCount")}</th>
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
                          {deck.commander_name}
                        </a>
                      </td>
                      <td>{deck.color_identity && deck.color_identity.length > 0 ? deck.color_identity.join("") : "—"}</td>
                      <td>{deck.num_decks.toLocaleString()}</td>
                      <td>{deck.card_count}</td>
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
