import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { apiDelete, apiGet, apiPostJson, ApiError } from "../api/client";
import { useSort } from "../hooks/useSort";
import type { CardList, CardListItem, ListComparisonResponse } from "../types/lists";
import type { ComparisonMode } from "../types/comparison";
import type { UserSettings } from "../types/settings";
import type { PriceProfile } from "../types/pricing";

const REFRESH_POLL_INTERVAL_MS = 3000;

// document.execCommand("copy") is deprecated but still works in insecure
// (plain HTTP) contexts where navigator.clipboard is unavailable - see
// handleCopyMissingToClipboard. Must run synchronously within the original
// click handler's call stack (not after an `await`) - some browsers only
// honor it as a trusted user gesture that way, which is why the caller
// never awaits anything before reaching this on the fallback path. Throws
// if the browser refuses it too, which the caller catches.
function copyViaFallback(text: string): void {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.top = "0";
  textarea.style.left = "0";
  textarea.style.opacity = "0";
  textarea.readOnly = true;
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, text.length);
  try {
    const ok = document.execCommand("copy");
    if (!ok) throw new Error("execCommand('copy') returned false");
  } finally {
    document.body.removeChild(textarea);
  }
}

export default function ListDetail() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [cardList, setCardList] = useState<CardList | null>(null);
  const [items, setItems] = useState<CardListItem[] | null>(null);
  const [comparison, setComparison] = useState<ListComparisonResponse | null>(null);
  const [mode, setMode] = useState<ComparisonMode>("oracle");
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const [priceProfiles, setPriceProfiles] = useState<PriceProfile[] | null>(null);
  const [priceProfileId, setPriceProfileId] = useState<string>("");
  const [budgetInput, setBudgetInput] = useState<string>("");
  const [pricingBusy, setPricingBusy] = useState(false);
  const [pricingError, setPricingError] = useState<string | null>(null);

  const [copyMissingState, setCopyMissingState] = useState<"idle" | "copied" | "error">("idle");

  const fetchAll = useCallback(
    (comparisonMode: ComparisonMode) => {
      if (!id) return;
      apiGet<CardList>(`/lists/${id}`)
        .then(setCardList)
        .catch((err: unknown) => setError(err instanceof ApiError ? err.message : String(err)));
      apiGet<CardListItem[]>(`/lists/${id}/items`)
        .then(setItems)
        .catch((err: unknown) => setError(err instanceof ApiError ? err.message : String(err)));
      apiGet<ListComparisonResponse>(`/lists/${id}/comparison?mode=${comparisonMode}`)
        .then(setComparison)
        .catch((err: unknown) => setError(err instanceof ApiError ? err.message : String(err)));
    },
    [id],
  );

  useEffect(() => {
    apiGet<PriceProfile[]>("/price-profiles")
      .then((profiles) => {
        setPriceProfiles(profiles);
        const defaultProfile = profiles.find((p) => p.is_default);
        if (defaultProfile) setPriceProfileId(String(defaultProfile.id));
      })
      .catch(() => {
        // Pricing stays opt-in and unavailable if this fails - not fatal to the page.
      });
  }, []);

  async function handleApplyPricing() {
    if (!id || !priceProfileId) return;
    setPricingBusy(true);
    setPricingError(null);
    try {
      const params = new URLSearchParams({ mode, price_profile_id: priceProfileId });
      if (budgetInput.trim()) params.set("budget", budgetInput.trim());
      const response = await apiGet<ListComparisonResponse>(`/lists/${id}/comparison?${params.toString()}`);
      setComparison(response);
    } catch (err) {
      setPricingError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setPricingBusy(false);
    }
  }

  // User-requested: a price indicator should be visible on this page without
  // an extra manual step. Pricing was previously opt-in (pick a profile,
  // click "Apply") because it costs extra DB round-trips - see
  // ListComparisonResponse's own docstring - but that cost is the same
  // whether triggered by a click or automatically, so this just does the
  // first `handleApplyPricing()`-equivalent call automatically once the
  // default profile is known, using whatever `comparison` a plain mode-
  // change fetch (fetchAll) already loaded. Re-fires after any fresh,
  // unpriced `comparison` (e.g. a mode switch), not just on first load.
  useEffect(() => {
    if (priceProfileId && comparison && comparison.priced_missing === null && !pricingBusy) {
      handleApplyPricing();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [priceProfileId, comparison, pricingBusy]);

  useEffect(() => {
    apiGet<UserSettings>("/settings")
      .then((settings) => {
        setMode(settings.default_comparison_mode);
        fetchAll(settings.default_comparison_mode);
      })
      .catch(() => fetchAll("oracle"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // While a refresh is in flight (this page or the periodic staleness sweep
  // triggered it), poll for completion instead of leaving a stale FETCHING
  // badge on screen forever - and once it lands, reload items/comparison
  // too (a content-changing refresh replaces the list's items wholesale).
  useEffect(() => {
    if (cardList?.refresh_status !== "FETCHING" || !id) return;
    const poll = setInterval(() => {
      apiGet<CardList>(`/lists/${id}`)
        .then((updated) => {
          setCardList(updated);
          if (updated.refresh_status !== "FETCHING") fetchAll(mode);
        })
        .catch(() => {
          // transient - next poll tick retries
        });
    }, REFRESH_POLL_INTERVAL_MS);
    return () => clearInterval(poll);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardList?.refresh_status, id]);

  function handleModeChange(newMode: ComparisonMode) {
    setMode(newMode);
    fetchAll(newMode);
  }

  async function handleRefresh() {
    if (!id) return;
    setRefreshing(true);
    setRefreshError(null);
    try {
      const updated = await apiPostJson<CardList>(`/lists/${id}/refresh`, {});
      setCardList(updated);
    } catch (err) {
      setRefreshError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }

  function flashCopyMissingState(state: "copied" | "error") {
    setCopyMissingState(state);
    setTimeout(() => setCopyMissingState("idle"), 2000);
  }

  function handleCopyMissingToClipboard() {
    if (!comparison || comparison.missing.length === 0) return;
    // "{quantity} {name}" per line, one card per line - matches
    // app.parsers.list_text's own accepted format (`^\d+x?\s+.+$`), so this
    // is also directly re-pasteable into CardForge's own manual text import
    // or another deckbuilder's decklist paste box, not just a display copy.
    const text = comparison.missing.map((m) => `${m.missing_quantity} ${m.name}`).join("\n");

    // navigator.clipboard is only available (and functional) in a secure
    // context (HTTPS or localhost) - this app is commonly reached over
    // plain HTTP on a LAN hostname (docker.trusted.local:666), where it's
    // simply absent. Go straight to the synchronous execCommand fallback
    // in that case rather than attempting (and always failing) the modern
    // API first.
    if (window.isSecureContext && navigator.clipboard) {
      navigator.clipboard.writeText(text).then(
        () => flashCopyMissingState("copied"),
        (err: unknown) => {
          try {
            copyViaFallback(text);
            flashCopyMissingState("copied");
          } catch (fallbackErr) {
            console.error("copy to clipboard failed", err, fallbackErr);
            flashCopyMissingState("error");
          }
        },
      );
      return;
    }

    try {
      copyViaFallback(text);
      flashCopyMissingState("copied");
    } catch (err) {
      console.error("copy to clipboard failed", err);
      flashCopyMissingState("error");
    }
  }

  async function handleDelete() {
    if (!id || !cardList) return;
    setDeleting(true);
    try {
      await apiDelete(`/lists/${id}`);
      navigate("/lists");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setDeleting(false);
    }
  }

  const totalMissingCost = comparison?.priced_missing
    ? comparison.priced_missing.reduce(
        (sum, p) => (p.unit_price !== null ? sum + Number(p.unit_price) * p.missing_quantity : sum),
        0,
      )
    : null;
  const unpricedMissingCount = comparison?.priced_missing
    ? comparison.priced_missing.filter((p) => p.unit_price === null).length
    : 0;
  const selectedProfileCurrency = priceProfiles?.find((p) => String(p.id) === priceProfileId)?.currency;

  const { sorted, sortKey, direction, toggleSort } = useSort<CardListItem>(items ?? [], "section", "asc");

  function sortIndicator(key: keyof CardListItem) {
    if (sortKey !== key) return "";
    return direction === "asc" ? " ▲" : " ▼";
  }

  if (error) {
    return (
      <div>
        <div className="cf-alert cf-alert-error">{error}</div>
      </div>
    );
  }

  if (!cardList || !items) {
    return <p>{t("common.loading")}</p>;
  }

  const refreshBadgeClass =
    cardList.refresh_status === "CURRENT" && !cardList.is_stale
      ? "cf-badge cf-badge-ok"
      : cardList.refresh_status === "FAILED" || cardList.refresh_status === "AUTH_REQUIRED"
        ? "cf-badge cf-badge-error"
        : "cf-badge cf-badge-warn";

  return (
    <div>
      <h2>
        {cardList.name} <span className="cf-badge">{t(`listsPage.types.${cardList.list_type}`)}</span>
      </h2>

      {cardList.source_url && (
        <div className="cf-card">
          {refreshError && <div className="cf-alert cf-alert-error">{refreshError}</div>}
          <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span>
              {t("listDetailPage.importedFrom")}{" "}
              <a href={cardList.source_url} target="_blank" rel="noreferrer">
                {t(`listsImportPage.sourceTypes.${cardList.source_type}`)}
              </a>
            </span>
            {cardList.refresh_status && (
              <span className={refreshBadgeClass}>
                {cardList.is_stale && cardList.refresh_status === "CURRENT"
                  ? t("listDetailPage.refreshStatus.STALE")
                  : t(`listDetailPage.refreshStatus.${cardList.refresh_status}`)}
              </span>
            )}
            {cardList.last_refreshed_at && (
              <span style={{ fontSize: 13, color: "var(--cf-muted)" }}>
                {t("listDetailPage.lastRefreshed")} {new Date(cardList.last_refreshed_at).toLocaleString()}
              </span>
            )}
            <button
              className="cf-btn"
              disabled={refreshing || cardList.refresh_status === "FETCHING"}
              onClick={handleRefresh}
            >
              {cardList.refresh_status === "FETCHING"
                ? t("listDetailPage.refreshing")
                : t("listDetailPage.refreshNow")}
            </button>
          </div>
          {cardList.refresh_status === "AUTH_REQUIRED" && (
            <div className="cf-alert cf-alert-warn">{t("listDetailPage.authRequiredHint")}</div>
          )}
          {cardList.refresh_status === "FAILED" && cardList.refresh_error && (
            <div className="cf-alert cf-alert-error">{cardList.refresh_error}</div>
          )}
        </div>
      )}

      {comparison && (
        <div className="cf-card">
          <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
            <label htmlFor="ld-mode" style={{ margin: 0 }}>
              {t("comparisonsPage.mode")}
            </label>
            <select
              id="ld-mode"
              className="cf-select"
              value={mode}
              onChange={(e) => handleModeChange(e.target.value as ComparisonMode)}
            >
              <option value="oracle">{t("comparisonsPage.modes.oracle")}</option>
              <option value="printing">{t("comparisonsPage.modes.printing")}</option>
            </select>
          </div>

          {priceProfiles && priceProfiles.length > 0 && (
            <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10, flexWrap: "wrap" }}>
              <div>
                <label htmlFor="ld-price-profile" style={{ display: "block" }}>
                  {t("listDetailPage.pricing.profile")}
                </label>
                <select
                  id="ld-price-profile"
                  className="cf-select"
                  value={priceProfileId}
                  onChange={(e) => setPriceProfileId(e.target.value)}
                >
                  <option value="">{t("listDetailPage.pricing.none")}</option>
                  {priceProfiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.currency})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="ld-budget" style={{ display: "block" }}>
                  {t("listDetailPage.pricing.budget")}
                </label>
                <input
                  id="ld-budget"
                  className="cf-input"
                  style={{ width: 100 }}
                  value={budgetInput}
                  onChange={(e) => setBudgetInput(e.target.value)}
                  placeholder={t("listDetailPage.pricing.budgetPlaceholder")}
                />
              </div>
              <button className="cf-btn" disabled={pricingBusy || !priceProfileId} onClick={handleApplyPricing}>
                {pricingBusy ? t("common.loading") : t("listDetailPage.pricing.apply")}
              </button>
            </div>
          )}
          {pricingError && <div className="cf-alert cf-alert-error">{pricingError}</div>}

          <div className={comparison.is_fully_buildable ? "cf-alert cf-alert-success" : "cf-alert cf-alert-warn"}>
            {comparison.is_fully_buildable
              ? t("comparisonsPage.buildable")
              : t("comparisonsPage.notBuildable")}
          </div>

          <div className="cf-stat-row">
            <div className="cf-stat">
              <div className="cf-stat-value">{comparison.total_required_cards}</div>
              <div className="cf-stat-label">{t("comparisonsPage.requiredCards")}</div>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{comparison.coverage_percent}%</div>
              <div className="cf-stat-label">{t("comparisonsPage.coverage")}</div>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{comparison.missing.length}</div>
              <div className="cf-stat-label">{t("comparisonsPage.missingCards")}</div>
            </div>
            {totalMissingCost !== null && (
              <div className="cf-stat">
                <div className="cf-stat-value">
                  {totalMissingCost.toFixed(2)} {selectedProfileCurrency}
                  {unpricedMissingCount > 0 && (
                    <span
                      style={{ fontSize: 13, color: "var(--cf-muted)", fontWeight: "normal" }}
                      title={t("listDetailPage.pricing.unpricedHint", { count: unpricedMissingCount })}
                    >
                      {" "}
                      (+{unpricedMissingCount})
                    </span>
                  )}
                </div>
                <div className="cf-stat-label">{t("listDetailPage.pricing.costToComplete")}</div>
              </div>
            )}
          </div>

          {comparison.missing.length > 0 && (
            <div className="cf-btn-row">
              <button className="cf-btn" onClick={handleCopyMissingToClipboard}>
                {copyMissingState === "copied"
                  ? t("listDetailPage.copyMissingDone")
                  : copyMissingState === "error"
                    ? t("listDetailPage.copyMissingError")
                    : t("listDetailPage.copyMissing")}
              </button>
            </div>
          )}

          {comparison.missing.length > 0 && (
            <div className="cf-table-wrap">
              <table className="cf-table">
                <thead>
                  <tr>
                    <th>{t("comparisonsPage.columns.name")}</th>
                    <th>{t("comparisonsPage.columns.required")}</th>
                    <th>{t("comparisonsPage.columns.owned")}</th>
                    <th>{t("comparisonsPage.columns.missing")}</th>
                    {comparison.priced_missing && <th>{t("listDetailPage.pricing.unitPrice")}</th>}
                  </tr>
                </thead>
                <tbody>
                  {comparison.missing.map((m) => {
                    const priced = comparison.priced_missing?.find((p) => p.name === m.name);
                    return (
                      <tr key={`${m.name}::${m.oracle_id ?? ""}`}>
                        <td>{m.name}</td>
                        <td>{m.required_quantity}</td>
                        <td>{m.owned_quantity}</td>
                        <td>{m.missing_quantity}</td>
                        {comparison.priced_missing && (
                          <td>
                            {priced?.unit_price
                              ? `${priced.unit_price} (${t(`pricesPage.providers.${priced.provider}`)})`
                              : t("listDetailPage.pricing.noPrice")}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {comparison.budget && (
            <div style={{ marginTop: 20 }}>
              <h3>{t("listDetailPage.pricing.budgetResultTitle")}</h3>
              <div
                className={comparison.budget.fully_covered ? "cf-alert cf-alert-success" : "cf-alert cf-alert-warn"}
              >
                {comparison.budget.fully_covered
                  ? t("listDetailPage.pricing.budgetFullyCovered")
                  : t("listDetailPage.pricing.budgetNotFullyCovered")}
              </div>
              <div className="cf-stat-row">
                <div className="cf-stat">
                  <div className="cf-stat-value">
                    {comparison.budget.total_spent} {comparison.budget.currency}
                  </div>
                  <div className="cf-stat-label">{t("listDetailPage.pricing.totalSpent")}</div>
                </div>
                <div className="cf-stat">
                  <div className="cf-stat-value">
                    {comparison.budget.remaining_budget} {comparison.budget.currency}
                  </div>
                  <div className="cf-stat-label">{t("listDetailPage.pricing.remainingBudget")}</div>
                </div>
                {comparison.budget.unpriced.length > 0 && (
                  <div className="cf-stat">
                    <div className="cf-stat-value">{comparison.budget.unpriced.length}</div>
                    <div className="cf-stat-label">{t("listDetailPage.pricing.unpriced")}</div>
                  </div>
                )}
              </div>
              <div className="cf-table-wrap">
                <table className="cf-table">
                  <thead>
                    <tr>
                      <th>{t("comparisonsPage.columns.name")}</th>
                      <th>{t("listDetailPage.pricing.unitPrice")}</th>
                      <th>{t("listDetailPage.pricing.affordable")}</th>
                      <th>{t("listDetailPage.pricing.lineTotal")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.budget.lines.map((line) => (
                      <tr key={line.name} className={line.affordable_quantity < line.missing_quantity ? "cf-row-error" : undefined}>
                        <td>{line.name}</td>
                        <td>{line.unit_price}</td>
                        <td>
                          {line.affordable_quantity} / {line.missing_quantity}
                        </td>
                        <td>{line.line_total}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="cf-card">
        {items.length === 0 ? (
          <p>{t("listDetailPage.empty")}</p>
        ) : (
          <div className="cf-table-wrap">
            <table className="cf-table">
              <thead>
                <tr>
                  <th className="cf-th-sortable" onClick={() => toggleSort("card_name")}>
                    {t("collection.columns.name")}
                    {sortIndicator("card_name")}
                  </th>
                  <th className="cf-th-sortable" onClick={() => toggleSort("section")}>
                    {t("listsImportPage.columns.section")}
                    {sortIndicator("section")}
                  </th>
                  <th className="cf-th-sortable" onClick={() => toggleSort("quantity")}>
                    {t("collection.columns.quantity")}
                    {sortIndicator("quantity")}
                  </th>
                  <th>{t("collection.columns.set")}</th>
                  <th>{t("listDetailPage.category")}</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((item) => (
                  <tr key={item.id}>
                    <td>{item.display_name}</td>
                    <td>{t(`listsImportPage.sections.${item.section}`)}</td>
                    <td>{item.quantity}</td>
                    <td>{item.set_code ?? item.set_name ?? "—"}</td>
                    <td>{item.category ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="cf-btn-row">
        <a className="cf-btn" href={`/api/lists/${id}/export.csv`} download>
          {t("listDetailPage.exportCsv")}
        </a>
        <button className="cf-btn" disabled={deleting} onClick={handleDelete}>
          {t("listDetailPage.delete")}
        </button>
      </div>
    </div>
  );
}
