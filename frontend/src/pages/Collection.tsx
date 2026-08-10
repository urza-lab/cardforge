import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, ApiError } from "../api/client";
import { useSort } from "../hooks/useSort";
import type { Collection as CollectionType, CollectionItem } from "../types/collection";

export default function Collection() {
  const { t } = useTranslation();
  const [collection, setCollection] = useState<CollectionType | null>(null);
  const [items, setItems] = useState<CollectionItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<CollectionType>("/collections/default")
      .then((fetchedCollection) => {
        if (cancelled) return undefined;
        setCollection(fetchedCollection);
        return apiGet<CollectionItem[]>(`/collections/${fetchedCollection.id}/items`);
      })
      .then((fetchedItems) => {
        if (!cancelled && fetchedItems) setItems(fetchedItems);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const totalCards = items?.reduce((sum, item) => sum + item.quantity, 0) ?? 0;
  const { sorted, sortKey, direction, toggleSort } = useSort<CollectionItem>(items ?? [], "card_name", "asc");

  function sortIndicator(key: keyof CollectionItem) {
    if (sortKey !== key) return "";
    return direction === "asc" ? " ▲" : " ▼";
  }

  return (
    <div>
      <h2>{t("nav.collection")}</h2>
      {error && <div className="cf-alert cf-alert-error">{error}</div>}
      {!error && !items && <p>{t("common.loading")}</p>}
      {items && (
        <div className="cf-card">
          <div className="cf-stat-row">
            <div className="cf-stat">
              <div className="cf-stat-value">{items.length}</div>
              <div className="cf-stat-label">{t("collection.distinctEntries")}</div>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{totalCards}</div>
              <div className="cf-stat-label">{t("collection.totalCards")}</div>
            </div>
          </div>

          {items.length === 0 ? (
            <p>
              {t("collection.empty")} <Link to="/collection/import">{t("nav.collectionImport")}</Link>
            </p>
          ) : (
            <>
              <div className="cf-table-wrap">
                <table className="cf-table">
                  <thead>
                    <tr>
                      <th className="cf-th-sortable" onClick={() => toggleSort("card_name")}>
                        {t("collection.columns.name")}
                        {sortIndicator("card_name")}
                      </th>
                      <th className="cf-th-sortable" onClick={() => toggleSort("set_code")}>
                        {t("collection.columns.set")}
                        {sortIndicator("set_code")}
                      </th>
                      <th>{t("collection.columns.number")}</th>
                      <th className="cf-th-sortable" onClick={() => toggleSort("quantity")}>
                        {t("collection.columns.quantity")}
                        {sortIndicator("quantity")}
                      </th>
                      <th>{t("collection.columns.foil")}</th>
                      <th>{t("collection.columns.condition")}</th>
                      <th>{t("collection.columns.language")}</th>
                      <th>{t("collection.columns.price")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((item) => (
                      <tr key={item.id}>
                        <td>{item.display_name}</td>
                        <td>{item.set_code ?? item.set_name ?? "—"}</td>
                        <td>{item.collector_number ?? "—"}</td>
                        <td>{item.quantity}</td>
                        <td>{item.foil ? t("common.yes") : t("common.no")}</td>
                        <td>{item.condition ?? "—"}</td>
                        <td>{item.language ?? "—"}</td>
                        <td>
                          {item.purchase_price
                            ? `${item.purchase_price} ${item.purchase_currency ?? ""}`.trim()
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {collection && (
                <div className="cf-btn-row">
                  <a className="cf-btn" href={`/api/collections/${collection.id}/export.csv`} download>
                    {t("collection.exportCsv")}
                  </a>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
