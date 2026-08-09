import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, apiPostForm, ApiError } from "../api/client";
import type { Collection } from "../types/collection";
import type { ComparisonMode, ComparisonResponse, DecklistSourceType } from "../types/comparison";
import type { UserSettings } from "../types/settings";

const SOURCE_TYPES: DecklistSourceType[] = ["text_list", "json", "generic_csv"];

export default function Comparisons() {
  const { t } = useTranslation();
  const [collection, setCollection] = useState<Collection | null>(null);
  const [sourceType, setSourceType] = useState<DecklistSourceType>("text_list");
  const [mode, setMode] = useState<ComparisonMode>("oracle");
  const [modeTouched, setModeTouched] = useState(false);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ComparisonResponse | null>(null);

  useEffect(() => {
    apiGet<Collection>("/collections/default")
      .then(setCollection)
      .catch(() => {
        // Surfaced when the user submits (button stays disabled otherwise).
      });
  }, []);

  useEffect(() => {
    // Seed the mode picker from the user's saved preference (Settings page)
    // — but only if they haven't already touched the dropdown this session.
    apiGet<UserSettings>("/settings")
      .then((settings) => {
        if (!modeTouched) setMode(settings.default_comparison_mode);
      })
      .catch(() => {
        // Non-fatal: the hardcoded "oracle" default from useState above stands.
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!collection) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      form.set("collection_id", String(collection.id));
      form.set("source_type", sourceType);
      form.set("mode", mode);
      if (file) {
        form.set("file", file);
      } else {
        form.set("text", text);
      }
      const response = await apiPostForm<ComparisonResponse>("/comparisons/run", form);
      setResult(response);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = !!collection && (text.trim().length > 0 || !!file) && !busy;

  return (
    <div>
      <h2>{t("nav.comparisons")}</h2>
      {error && <div className="cf-alert cf-alert-error">{error}</div>}

      <form className="cf-card" onSubmit={handleSubmit}>
        <div className="cf-form-row">
          <label htmlFor="cmp-source-type">{t("comparisonsPage.sourceType")}</label>
          <select
            id="cmp-source-type"
            className="cf-select"
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value as DecklistSourceType)}
          >
            {SOURCE_TYPES.map((type) => (
              <option key={type} value={type}>
                {t(`comparisonsPage.sourceTypes.${type}`)}
              </option>
            ))}
          </select>
        </div>

        <div className="cf-form-row">
          <label htmlFor="cmp-mode">{t("comparisonsPage.mode")}</label>
          <select
            id="cmp-mode"
            className="cf-select"
            value={mode}
            onChange={(e) => {
              setMode(e.target.value as ComparisonMode);
              setModeTouched(true);
            }}
          >
            <option value="oracle">{t("comparisonsPage.modes.oracle")}</option>
            <option value="printing">{t("comparisonsPage.modes.printing")}</option>
          </select>
        </div>

        <div className="cf-form-row">
          <label htmlFor="cmp-text">{t("comparisonsPage.pasteList")}</label>
          <textarea
            id="cmp-text"
            className="cf-textarea"
            rows={8}
            placeholder={t("comparisonsPage.placeholder")}
            value={text}
            disabled={!!file}
            onChange={(e) => setText(e.target.value)}
          />
        </div>

        <div className="cf-form-row">
          <label htmlFor="cmp-file">{t("comparisonsPage.orUploadFile")}</label>
          <input
            id="cmp-file"
            type="file"
            accept=".txt,.json,.csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>

        <div className="cf-btn-row">
          <button type="submit" className="cf-btn cf-btn-primary" disabled={!canSubmit}>
            {busy ? t("common.loading") : t("comparisonsPage.run")}
          </button>
        </div>
      </form>

      {result && (
        <div className="cf-card">
          <div className={result.is_fully_buildable ? "cf-alert cf-alert-success" : "cf-alert cf-alert-warn"}>
            {result.is_fully_buildable ? t("comparisonsPage.buildable") : t("comparisonsPage.notBuildable")}
          </div>

          <div className="cf-stat-row">
            <div className="cf-stat">
              <div className="cf-stat-value">{result.total_required_cards}</div>
              <div className="cf-stat-label">{t("comparisonsPage.requiredCards")}</div>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{result.coverage_percent}%</div>
              <div className="cf-stat-label">{t("comparisonsPage.coverage")}</div>
            </div>
            <div className="cf-stat">
              <div className="cf-stat-value">{result.missing.length}</div>
              <div className="cf-stat-label">{t("comparisonsPage.missingCards")}</div>
            </div>
          </div>

          {result.missing.length > 0 && (
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
                  {result.missing.map((m) => (
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

          {result.row_errors.length > 0 && (
            <>
              <h3>{t("comparisonsPage.rowErrors")}</h3>
              <div className="cf-table-wrap">
                <table className="cf-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>{t("comparisonsPage.columns.detail")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.row_errors.map((e) => (
                      <tr key={e.row_number} className="cf-row-error">
                        <td>{e.row_number}</td>
                        <td>{e.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
