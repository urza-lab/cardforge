import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { apiGet, ApiError } from "../api/client";
import { useSort } from "../hooks/useSort";
import type { CardList, CardListItem, ListComparisonResponse } from "../types/lists";
import type { ComparisonMode } from "../types/comparison";
import type { UserSettings } from "../types/settings";

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
    apiGet<UserSettings>("/settings")
      .then((settings) => {
        setMode(settings.default_comparison_mode);
        fetchAll(settings.default_comparison_mode);
      })
      .catch(() => fetchAll("oracle"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  function handleModeChange(newMode: ComparisonMode) {
    setMode(newMode);
    fetchAll(newMode);
  }

  async function handleDelete() {
    if (!id || !cardList) return;
    setDeleting(true);
    try {
      const resp = await fetch(`/api/lists/${id}`, { method: "DELETE" });
      if (!resp.ok) throw new ApiError(resp.status, `delete failed with ${resp.status}`);
      navigate("/lists");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setDeleting(false);
    }
  }

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

  return (
    <div>
      <h2>
        {cardList.name} <span className="cf-badge">{t(`listsPage.types.${cardList.list_type}`)}</span>
      </h2>

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
          </div>

          {comparison.missing.length > 0 && (
            <div className="cf-table-wrap">
              <table className="cf-table">
                <thead>
                  <tr>
                    <th>{t("comparisonsPage.columns.name")}</th>
                    <th>{t("comparisonsPage.columns.required")}</th>
                    <th>{t("comparisonsPage.columns.owned")}</th>
                    <th>{t("comparisonsPage.columns.missing")}</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.missing.map((m) => (
                    <tr key={`${m.name}::${m.oracle_id ?? ""}`}>
                      <td>{m.name}</td>
                      <td>{m.required_quantity}</td>
                      <td>{m.owned_quantity}</td>
                      <td>{m.missing_quantity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
