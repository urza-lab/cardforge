import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, ApiError } from "../api/client";
import type { Collection as CollectionType, CollectionItem } from "../types/collection";

export default function Collection() {
  const { t } = useTranslation();
  const [items, setItems] = useState<CollectionItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<CollectionType>("/collections/default")
      .then((collection) => apiGet<CollectionItem[]>(`/collections/${collection.id}/items`))
      .then((fetchedItems) => {
        if (!cancelled) setItems(fetchedItems);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const totalCards = items?.reduce((sum, item) => sum + item.quantity, 0) ?? 0;

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
            <div className="cf-table-wrap">
              <table className="cf-table">
                <thead>
                  <tr>
                    <th>{t("collection.columns.name")}</th>
                    <th>{t("collection.columns.set")}</th>
                    <th>{t("collection.columns.number")}</th>
                    <th>{t("collection.columns.quantity")}</th>
                    <th>{t("collection.columns.foil")}</th>
                    <th>{t("collection.columns.condition")}</th>
                    <th>{t("collection.columns.language")}</th>
                    <th>{t("collection.columns.price")}</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td>{item.card_name}</td>
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
          )}
        </div>
      )}
    </div>
  );
}
