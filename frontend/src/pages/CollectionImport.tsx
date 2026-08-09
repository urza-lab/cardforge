import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, apiPostForm, apiPostJson, ApiError } from "../api/client";
import type { Collection } from "../types/collection";
import type { ImportPreview, ImportSourceType, ImportSummary } from "../types/imports";

const SOURCE_TYPES: ImportSourceType[] = ["manabox_csv", "generic_csv", "text_list", "json"];

export default function CollectionImport() {
  const { t } = useTranslation();
  const [collection, setCollection] = useState<Collection | null>(null);
  const [sourceType, setSourceType] = useState<ImportSourceType>("manabox_csv");
  const [file, setFile] = useState<File | null>(null);
  const [columnMapping, setColumnMapping] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [skipBadRows, setSkipBadRows] = useState(false);
  const [result, setResult] = useState<ImportSummary | null>(null);

  useEffect(() => {
    apiGet<Collection>("/collections/default")
      .then(setCollection)
      .catch(() => {
        // Surfaced when the user actually tries to submit (button stays disabled otherwise).
      });
  }, []);

  async function handlePreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!collection || !file) return;
    setBusy(true);
    setFormError(null);
    try {
      const form = new FormData();
      form.set("source_type", sourceType);
      form.set("collection_id", String(collection.id));
      form.set("file", file);
      if (sourceType === "generic_csv" && columnMapping.trim()) {
        form.set("column_mapping", columnMapping.trim());
      }
      const response = await apiPostForm<ImportPreview>("/imports/preview", form);
      setPreview(response);
      setSkipBadRows(false);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm() {
    if (!preview) return;
    setBusy(true);
    setFormError(null);
    try {
      const response = await apiPostJson<ImportSummary>(`/imports/${preview.id}/confirm`, {
        skip_bad_rows: skipBadRows,
      });
      setResult(response);
      setPreview(null);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleAbort() {
    if (!preview) return;
    setBusy(true);
    setFormError(null);
    try {
      const response = await apiPostJson<ImportSummary>(`/imports/${preview.id}/abort`, {});
      setResult(response);
      setPreview(null);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function startOver() {
    setPreview(null);
    setResult(null);
    setFile(null);
    setColumnMapping("");
    setFormError(null);
  }

  return (
    <div>
      <h2>{t("nav.collectionImport")}</h2>

      {formError && <div className="cf-alert cf-alert-error">{formError}</div>}

      {!preview && !result && (
        <form className="cf-card" onSubmit={handlePreview}>
          <div className="cf-form-row">
            <label htmlFor="source-type">{t("importPage.sourceType")}</label>
            <select
              id="source-type"
              className="cf-select"
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value as ImportSourceType)}
            >
              {SOURCE_TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(`importPage.sourceTypes.${type}`)}
                </option>
              ))}
            </select>
          </div>

          <div className="cf-form-row">
            <label htmlFor="import-file">{t("importPage.file")}</label>
            <input
              id="import-file"
              type="file"
              accept=".csv,.txt,.json"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>

          {sourceType === "generic_csv" && (
            <div className="cf-form-row">
              <label htmlFor="column-mapping">{t("importPage.columnMapping")}</label>
              <textarea
                id="column-mapping"
                className="cf-textarea"
                rows={3}
                placeholder='{"name": "Card", "quantity": "Qty"}'
                value={columnMapping}
                onChange={(e) => setColumnMapping(e.target.value)}
              />
            </div>
          )}

          <div className="cf-btn-row">
            <button type="submit" className="cf-btn cf-btn-primary" disabled={!file || !collection || busy}>
              {busy ? t("common.loading") : t("importPage.preview")}
            </button>
          </div>
        </form>
      )}

      {preview && (
        <div className="cf-card">
          {preview.is_likely_duplicate && (
            <div className="cf-alert cf-alert-warn">{t("importPage.duplicateWarning")}</div>
          )}

          <div className="cf-stat-row">
            <div className="cf-stat">
              <div className="cf-stat-value">{preview.total_rows}</div>
              <div className="cf-stat-label">{t("importPage.totalRows")}</div>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{preview.valid_rows}</div>
              <div className="cf-stat-label">{t("importPage.validRows")}</div>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{preview.error_rows}</div>
              <div className="cf-stat-label">{t("importPage.errorRows")}</div>
            </div>
          </div>

          <div className="cf-table-wrap">
            <table className="cf-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{t("importPage.columns.status")}</th>
                  <th>{t("importPage.columns.name")}</th>
                  <th>{t("importPage.columns.quantity")}</th>
                  <th>{t("importPage.columns.detail")}</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => (
                  <tr key={row.row_number} className={row.status === "error" ? "cf-row-error" : undefined}>
                    <td>{row.row_number}</td>
                    <td>
                      <span
                        className={row.status === "error" ? "cf-badge cf-badge-error" : "cf-badge cf-badge-ok"}
                      >
                        {row.status === "error" ? t("importPage.status.error") : t("importPage.status.ok")}
                      </span>
                    </td>
                    <td>{(row.mapped_data?.name as string | undefined) ?? "—"}</td>
                    <td>{(row.mapped_data?.quantity as number | undefined) ?? "—"}</td>
                    <td>{row.error_reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {preview.error_rows > 0 && (
            <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "center", marginTop: 14 }}>
              <input
                id="skip-bad-rows"
                type="checkbox"
                checked={skipBadRows}
                onChange={(e) => setSkipBadRows(e.target.checked)}
              />
              <label htmlFor="skip-bad-rows">
                {t("importPage.skipBadRows", { count: preview.error_rows })}
              </label>
            </div>
          )}

          <div className="cf-btn-row">
            <button
              className="cf-btn cf-btn-primary"
              disabled={busy || (preview.error_rows > 0 && !skipBadRows)}
              onClick={handleConfirm}
            >
              {t("importPage.confirm")}
            </button>
            <button className="cf-btn" disabled={busy} onClick={handleAbort}>
              {t("importPage.abort")}
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="cf-card">
          <div className={result.status === "aborted" ? "cf-alert cf-alert-warn" : "cf-alert cf-alert-success"}>
            {result.status === "aborted"
              ? t("importPage.aborted")
              : t("importPage.confirmed", { count: result.imported_rows })}
          </div>
          <div className="cf-btn-row">
            <button className="cf-btn cf-btn-primary" onClick={startOver}>
              {t("importPage.importAnother")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
