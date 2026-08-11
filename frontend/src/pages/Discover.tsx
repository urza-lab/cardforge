import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, apiPostJson, ApiError } from "../api/client";
import type { DeckDiscoverySyncStatusRead, PopularDeck } from "../types/discover";
import type { CardList, ListImportPreview, ListImportSummary } from "../types/lists";
import type { PriceProfile } from "../types/pricing";

const POLL_INTERVAL_MS = 3000;

type ImportState = "idle" | "importing" | "done" | "error";

async function importDeck(deck: PopularDeck): Promise<{ listId: number } | { error: string }> {
  try {
    const list = await apiPostJson<CardList>("/lists", { name: deck.name, list_type: "deck" });
    const preview = await apiPostJson<ListImportPreview>("/list-imports/preview-url", {
      list_id: list.id,
      url: deck.source_url,
    });
    await apiPostJson<ListImportSummary>(`/list-imports/${preview.id}/confirm`, { skip_bad_rows: true });
    return { listId: list.id };
  } catch (err) {
    return { error: err instanceof ApiError ? err.message : String(err) };
  }
}

export default function Discover() {
  const { t } = useTranslation();

  const [status, setStatus] = useState<DeckDiscoverySyncStatusRead | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const [decks, setDecks] = useState<PopularDeck[] | null>(null);
  const [decksError, setDecksError] = useState<string | null>(null);
  const [sort, setSort] = useState<"views" | "likes">("views");
  const [colorFilter, setColorFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState<"" | "moxfield" | "archidekt">("");
  const [bracketFilter, setBracketFilter] = useState("");

  const [importState, setImportState] = useState<Record<number, ImportState>>({});
  const [importResult, setImportResult] = useState<Record<number, { listId: number } | { error: string }>>({});

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ done: number; total: number } | null>(null);

  const [priceProfileId, setPriceProfileId] = useState<number | null>(null);
  const [pricingState, setPricingState] = useState<Record<number, "pricing" | "error">>({});
  const [pricingError, setPricingError] = useState<Record<number, string>>({});

  const fetchStatus = useCallback(() => {
    apiGet<DeckDiscoverySyncStatusRead>("/discover/decks/status")
      .then(setStatus)
      .catch((err: unknown) => setStatusError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  const fetchDecks = useCallback(() => {
    const params = new URLSearchParams({ sort });
    if (colorFilter.trim()) params.set("color_identity", colorFilter.trim().toUpperCase());
    if (sourceFilter) params.set("source", sourceFilter);
    if (bracketFilter) params.set("bracket", bracketFilter);
    apiGet<PopularDeck[]>(`/discover/decks?${params.toString()}`)
      .then(setDecks)
      .catch((err: unknown) => setDecksError(err instanceof ApiError ? err.message : String(err)));
  }, [sort, colorFilter, sourceFilter, bracketFilter]);

  useEffect(fetchStatus, [fetchStatus]);
  useEffect(fetchDecks, [fetchDecks]);

  useEffect(() => {
    apiGet<PriceProfile[]>("/price-profiles")
      .then((profiles) => {
        const defaultProfile = profiles.find((p) => p.is_default) ?? profiles[0];
        if (defaultProfile) setPriceProfileId(defaultProfile.id);
      })
      .catch(() => {
        // Lazy pricing stays unavailable (button hidden) if this fails - not fatal to the page.
      });
  }, []);

  useEffect(() => {
    // The deck list just changed (new sort/filter, or a fresh sync) - drop
    // any selection that no longer refers to a visible row.
    setSelected((prev) => {
      if (!decks) return prev;
      const visible = new Set(decks.map((d) => d.id));
      const next = new Set([...prev].filter((id) => visible.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [decks]);

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
    const result = await importDeck(deck);
    setImportState((s) => ({ ...s, [deck.id]: "error" in result ? "error" : "done" }));
    setImportResult((r) => ({ ...r, [deck.id]: result }));
  }

  async function handlePriceDeck(deck: PopularDeck) {
    if (!priceProfileId) return;
    setPricingState((s) => ({ ...s, [deck.id]: "pricing" }));
    try {
      const priced = await apiPostJson<PopularDeck>(`/discover/decks/${deck.id}/price`, {
        price_profile_id: priceProfileId,
      });
      setDecks((prev) => (prev ? prev.map((d) => (d.id === priced.id ? priced : d)) : prev));
      setPricingState((s) => {
        const next = { ...s };
        delete next[deck.id];
        return next;
      });
    } catch (err) {
      setPricingState((s) => ({ ...s, [deck.id]: "error" }));
      setPricingError((e) => ({ ...e, [deck.id]: err instanceof ApiError ? err.message : String(err) }));
    }
  }

  const selectableDecks = useMemo(
    () => (decks ?? []).filter((d) => importState[d.id] !== "done"),
    [decks, importState]
  );
  const allSelectableSelected =
    selectableDecks.length > 0 && selectableDecks.every((d) => selected.has(d.id));

  function toggleOne(deckId: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(deckId)) next.delete(deckId);
      else next.add(deckId);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelectableSelected ? new Set() : new Set(selectableDecks.map((d) => d.id)));
  }

  async function handleBulkImport() {
    const targets = (decks ?? []).filter((d) => selected.has(d.id) && importState[d.id] !== "done");
    if (targets.length === 0) return;

    setBulkRunning(true);
    setBulkProgress({ done: 0, total: targets.length });
    for (let i = 0; i < targets.length; i++) {
      const deck = targets[i];
      setImportState((s) => ({ ...s, [deck.id]: "importing" }));
      const result = await importDeck(deck);
      setImportState((s) => ({ ...s, [deck.id]: "error" in result ? "error" : "done" }));
      setImportResult((r) => ({ ...r, [deck.id]: result }));
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
        {status?.status === "CURRENT" && status.error_message && (
          <div className="cf-alert cf-alert-warn">{status.error_message}</div>
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
            <label htmlFor="disc-source">{t("discoverPage.source")}</label>
            <select
              id="disc-source"
              className="cf-select"
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value as "" | "moxfield" | "archidekt")}
            >
              <option value="">{t("discoverPage.sourceAll")}</option>
              <option value="moxfield">{t("discoverPage.sourceMoxfield")}</option>
              <option value="archidekt">{t("discoverPage.sourceArchidekt")}</option>
            </select>
          </div>
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
          <div>
            <label htmlFor="disc-bracket">{t("discoverPage.bracketFilter")}</label>
            <select id="disc-bracket" className="cf-select" value={bracketFilter} onChange={(e) => setBracketFilter(e.target.value)}>
              <option value="">{t("discoverPage.bracketAll")}</option>
              <option value="1">1</option>
              <option value="2">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5</option>
            </select>
          </div>
        </div>
        {bracketFilter && <p style={{ fontSize: 12, color: "var(--cf-muted)" }}>{t("discoverPage.bracketHint")}</p>}

        {decksError && <div className="cf-alert cf-alert-error">{decksError}</div>}
        {!decks && !decksError && <p>{t("common.loading")}</p>}
        {decks && decks.length === 0 && <p>{t("discoverPage.empty")}</p>}

        {decks && decks.length > 0 && (
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
                    <th>{t("discoverPage.columns.source")}</th>
                    <th>{t("discoverPage.columns.author")}</th>
                    <th>{t("discoverPage.columns.colors")}</th>
                    <th>{t("discoverPage.columns.bracket")}</th>
                    <th>{t("discoverPage.columns.views")}</th>
                    <th>{t("discoverPage.columns.likes")}</th>
                    <th>{t("discoverPage.columns.price")}</th>
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
                          <input
                            type="checkbox"
                            disabled={state === "done"}
                            checked={selected.has(deck.id)}
                            onChange={() => toggleOne(deck.id)}
                          />
                        </td>
                        <td>
                          <a href={deck.source_url} target="_blank" rel="noreferrer">
                            {deck.name}
                          </a>
                        </td>
                        <td>{t(`discoverPage.source${deck.source === "archidekt" ? "Archidekt" : "Moxfield"}`)}</td>
                        <td>{deck.author ?? "—"}</td>
                        <td>{deck.color_identity && deck.color_identity.length > 0 ? deck.color_identity.join("") : "—"}</td>
                        <td>{deck.bracket ?? "—"}</td>
                        <td>{deck.view_count.toLocaleString()}</td>
                        <td>{deck.like_count > 0 ? deck.like_count.toLocaleString() : "—"}</td>
                        <td>
                          {pricingState[deck.id] === "pricing" ? (
                            t("common.loading")
                          ) : deck.priced_at ? (
                            <span>
                              {deck.coverage_percent?.toFixed(0)}% ·{" "}
                              {deck.missing_cost !== null
                                ? `${Number(deck.missing_cost).toFixed(2)} ${deck.missing_cost_currency}`
                                : "—"}
                              {!!deck.unpriced_missing_count && (
                                <span
                                  style={{ color: "var(--cf-muted)" }}
                                  title={t("discoverPage.unpricedHint", { count: deck.unpriced_missing_count })}
                                >
                                  {" "}
                                  ({t("discoverPage.unpricedShort", { count: deck.unpriced_missing_count })})
                                </span>
                              )}
                            </span>
                          ) : (
                            <button
                              className="cf-btn"
                              disabled={!priceProfileId}
                              title={pricingState[deck.id] === "error" ? pricingError[deck.id] : undefined}
                              onClick={() => handlePriceDeck(deck)}
                            >
                              {t("discoverPage.priceDeck")}
                            </button>
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
          </>
        )}
      </div>
    </div>
  );
}
