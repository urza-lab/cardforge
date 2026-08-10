import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, apiPostJson, ApiError } from "../api/client";
import { useSort } from "../hooks/useSort";
import type { CardList, ListType } from "../types/lists";

export default function Lists() {
  const { t } = useTranslation();
  const [lists, setLists] = useState<CardList[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [listType, setListType] = useState<ListType>("deck");
  const [creating, setCreating] = useState(false);

  function reload() {
    apiGet<CardList[]>("/lists")
      .then(setLists)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : String(err)));
  }

  useEffect(reload, []);

  const { sorted, sortKey, direction, toggleSort } = useSort<CardList>(lists ?? [], "created_at", "desc");

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

  function sortIndicator(key: keyof CardList) {
    if (sortKey !== key) return "";
    return direction === "asc" ? " ▲" : " ▼";
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
          <div className="cf-table-wrap">
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
                  <th className="cf-th-sortable" onClick={() => toggleSort("created_at")}>
                    {t("listsPage.columns.created")}
                    {sortIndicator("created_at")}
                  </th>
                  <th>{t("sourcesPage.columns.status")}</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <Link to={`/lists/${item.id}`}>{item.name}</Link>
                    </td>
                    <td>{t(`listsPage.types.${item.list_type}`)}</td>
                    <td>{new Date(item.created_at).toLocaleDateString()}</td>
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
        )}
      </div>
    </div>
  );
}
