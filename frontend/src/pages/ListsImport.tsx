import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { apiGet, apiPatchJson, apiPostForm, apiPostJson, ApiError } from "../api/client";
import type { CardList, ListImportPreview, ListImportSourceType, ListImportSummary, ListType } from "../types/lists";

const SOURCE_TYPES: ListImportSourceType[] = ["text", "json", "csv"];
const FILE_ACCEPT: Record<ListImportSourceType, string> = {
  text: ".txt",
  json: ".json",
  csv: ".csv",
  moxfield: "",
  archidekt: "",
};
const NEW_LIST_VALUE = "__new__";
type ImportMode = "file" | "url";
type BulkUrlState = "idle" | "importing" | "done" | "error";
type BulkUrlResult = { listId: number; name: string } | { error: string };

// A placeholder name shown only for the moment between creating the list
// and confirming its import - renamed to the source's own real deck name
// right after (see importOneUrl), or left as this fallback if that name
// wasn't available (e.g. the fetch itself failed).
function nameFromUrl(url: string): string {
  try {
    const parts = new URL(url).pathname.split("/").filter(Boolean);
    const last = decodeURIComponent(parts[parts.length - 1] ?? "").replace(/[-_]+/g, " ").trim();
    return last || url;
  } catch {
    return url;
  }
}

async function importOneUrl(url: string): Promise<BulkUrlResult> {
  const placeholderName = nameFromUrl(url);
  try {
    const list = await apiPostJson<CardList>("/lists", { name: placeholderName, list_type: "deck" });
    const preview = await apiPostJson<ListImportPreview>("/list-imports/preview-url", { list_id: list.id, url });
    await apiPostJson<ListImportSummary>(`/list-imports/${preview.id}/confirm`, { skip_bad_rows: true });

    let finalName = placeholderName;
    if (preview.deck_name && preview.deck_name !== placeholderName) {
      try {
        const renamed = await apiPatchJson<CardList>(`/lists/${list.id}`, { name: preview.deck_name });
        finalName = renamed.name;
      } catch {
        // Import already succeeded - a rename failure shouldn't be reported as an import failure.
      }
    }
    return { listId: list.id, name: finalName };
  } catch (err) {
    return { error: err instanceof ApiError ? err.message : String(err) };
  }
}

export default function ListsImport() {
  const { t } = useTranslation();
  const [lists, setLists] = useState<CardList[] | null>(null);
  const [selectedListId, setSelectedListId] = useState<string>("");
  const [newListName, setNewListName] = useState("");
  const [newListType, setNewListType] = useState<ListType>("deck");

  const [mode, setMode] = useState<ImportMode>("file");
  const [sourceType, setSourceType] = useState<ListImportSourceType>("text");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ListImportPreview | null>(null);
  const [skipBadRows, setSkipBadRows] = useState(false);
  const [result, setResult] = useState<ListImportSummary | null>(null);
  const [resultListId, setResultListId] = useState<number | null>(null);

  const [multiUrl, setMultiUrl] = useState(false);
  const [bulkUrls, setBulkUrls] = useState("");
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkState, setBulkState] = useState<Record<number, BulkUrlState>>({});
  const [bulkResults, setBulkResults] = useState<Record<number, BulkUrlResult>>({});

  useEffect(() => {
    apiGet<CardList[]>("/lists")
      .then(setLists)
      .catch(() => {
        // Surfaced when the user submits (button stays disabled otherwise).
      });
  }, []);

  async function resolveListId(): Promise<number | null> {
    if (selectedListId && selectedListId !== NEW_LIST_VALUE) return Number(selectedListId);
    if (!newListName.trim()) return null;
    const created = await apiPostJson<CardList>("/lists", {
      name: newListName.trim(),
      list_type: newListType,
    });
    return created.id;
  }

  async function handlePreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setFormError(null);
    try {
      const listId = await resolveListId();
      if (listId === null) {
        setFormError(t("listsImportPage.needsList"));
        return;
      }

      if (mode === "url") {
        const response = await apiPostJson<ListImportPreview>("/list-imports/preview-url", {
          list_id: listId,
          url: url.trim(),
        });
        setPreview(response);
        setSkipBadRows(false);
        return;
      }

      const form = new FormData();
      form.set("source_type", sourceType);
      form.set("list_id", String(listId));
      if (file) {
        form.set("file", file);
      } else {
        form.set("file", new File([text], "pasted." + (sourceType === "json" ? "json" : "txt")));
      }
      const response = await apiPostForm<ListImportPreview>("/list-imports/preview", form);
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
      const response = await apiPostJson<ListImportSummary>(`/list-imports/${preview.id}/confirm`, {
        skip_bad_rows: skipBadRows,
      });
      setResult(response);
      setResultListId(preview.list_id);
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
      const response = await apiPostJson<ListImportSummary>(`/list-imports/${preview.id}/abort`, {});
      setResult(response);
      setResultListId(preview.list_id);
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
    setResultListId(null);
    setFile(null);
    setText("");
    setUrl("");
    setFormError(null);
    setBulkUrls("");
    setBulkState({});
    setBulkResults({});
  }

  const bulkUrlLines = bulkUrls
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  async function handleBulkUrlImport() {
    if (bulkUrlLines.length === 0) return;
    setBulkRunning(true);
    setBulkState({});
    setBulkResults({});
    for (let i = 0; i < bulkUrlLines.length; i++) {
      setBulkState((s) => ({ ...s, [i]: "importing" }));
      const outcome = await importOneUrl(bulkUrlLines[i]);
      setBulkState((s) => ({ ...s, [i]: "error" in outcome ? "error" : "done" }));
      setBulkResults((r) => ({ ...r, [i]: outcome }));
    }
    setBulkRunning(false);
  }

  const hasTargetList = selectedListId === NEW_LIST_VALUE ? !!newListName.trim() : !!selectedListId;
  const canSubmit =
    mode === "url" && multiUrl
      ? false // bulk mode has its own submit button (handleBulkUrlImport), not this form's
      : hasTargetList && (mode === "url" ? !!url.trim() : !!text.trim() || !!file);

  return (
    <div>
      <h2>{t("nav.listsImport")}</h2>
      {formError && <div className="cf-alert cf-alert-error">{formError}</div>}

      {!preview && !result && (
        <form className="cf-card" onSubmit={handlePreview}>
          {!(mode === "url" && multiUrl) && (
            <div className="cf-form-row">
              <label htmlFor="li-list">{t("listsImportPage.targetList")}</label>
              <select
                id="li-list"
                className="cf-select"
                value={selectedListId}
                onChange={(e) => setSelectedListId(e.target.value)}
              >
                <option value="" disabled>
                  {t("listsImportPage.chooseList")}
                </option>
                {lists?.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name} ({t(`listsPage.types.${l.list_type}`)})
                  </option>
                ))}
                <option value={NEW_LIST_VALUE}>{t("listsImportPage.newList")}</option>
              </select>
            </div>
          )}

          {!(mode === "url" && multiUrl) && selectedListId === NEW_LIST_VALUE && (
            <div className="cf-form-row" style={{ flexDirection: "row", gap: 10 }}>
              <input
                className="cf-input"
                style={{ flex: 1 }}
                value={newListName}
                onChange={(e) => setNewListName(e.target.value)}
                placeholder={t("listsPage.namePlaceholder")}
              />
              <select
                className="cf-select"
                value={newListType}
                onChange={(e) => setNewListType(e.target.value as ListType)}
              >
                <option value="deck">{t("listsPage.types.deck")}</option>
                <option value="cube">{t("listsPage.types.cube")}</option>
              </select>
            </div>
          )}

          <div className="cf-form-row" style={{ flexDirection: "row", gap: 16 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, margin: 0 }}>
              <input
                type="radio"
                name="li-mode"
                checked={mode === "file"}
                onChange={() => setMode("file")}
              />
              {t("listsImportPage.modeFile")}
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 6, margin: 0 }}>
              <input type="radio" name="li-mode" checked={mode === "url"} onChange={() => setMode("url")} />
              {t("listsImportPage.modeUrl")}
            </label>
          </div>

          {mode === "file" && (
            <>
              <div className="cf-form-row">
                <label htmlFor="li-source-type">{t("importPage.sourceType")}</label>
                <select
                  id="li-source-type"
                  className="cf-select"
                  value={sourceType}
                  onChange={(e) => setSourceType(e.target.value as ListImportSourceType)}
                >
                  {SOURCE_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {t(`listsImportPage.sourceTypes.${type}`)}
                    </option>
                  ))}
                </select>
              </div>

              <div className="cf-form-row">
                <label htmlFor="li-text">{t("comparisonsPage.pasteList")}</label>
                <textarea
                  id="li-text"
                  className="cf-textarea"
                  rows={8}
                  placeholder={t("listsImportPage.placeholder")}
                  value={text}
                  disabled={!!file}
                  onChange={(e) => setText(e.target.value)}
                />
              </div>

              <div className="cf-form-row">
                <label htmlFor="li-file">{t("comparisonsPage.orUploadFile")}</label>
                <input
                  id="li-file"
                  type="file"
                  accept={FILE_ACCEPT[sourceType]}
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </div>
            </>
          )}

          {mode === "url" && (
            <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <input
                id="li-multi-url"
                type="checkbox"
                checked={multiUrl}
                onChange={(e) => setMultiUrl(e.target.checked)}
              />
              <label htmlFor="li-multi-url" style={{ margin: 0 }}>{t("listsImportPage.multiUrl")}</label>
            </div>
          )}

          {mode === "url" && !multiUrl && (
            <div className="cf-form-row">
              <label htmlFor="li-url">{t("listsImportPage.urlLabel")}</label>
              <input
                id="li-url"
                type="url"
                className="cf-input"
                style={{ width: "100%" }}
                placeholder="https://moxfield.com/decks/... or https://archidekt.com/decks/..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
              <p style={{ fontSize: 13, color: "var(--cf-muted)" }}>{t("listsImportPage.urlHint")}</p>
            </div>
          )}

          {mode === "url" && multiUrl && (
            <div className="cf-form-row">
              <label htmlFor="li-bulk-urls">{t("listsImportPage.multiUrlLabel")}</label>
              <textarea
                id="li-bulk-urls"
                className="cf-textarea"
                rows={6}
                placeholder={"https://moxfield.com/decks/...\nhttps://archidekt.com/decks/...\n..."}
                value={bulkUrls}
                disabled={bulkRunning}
                onChange={(e) => setBulkUrls(e.target.value)}
              />
              <p style={{ fontSize: 13, color: "var(--cf-muted)" }}>{t("listsImportPage.multiUrlHint")}</p>
            </div>
          )}

          {!(mode === "url" && multiUrl) && (
            <div className="cf-btn-row">
              <button type="submit" className="cf-btn cf-btn-primary" disabled={!canSubmit || busy}>
                {busy ? t("common.loading") : t("importPage.preview")}
              </button>
            </div>
          )}
        </form>
      )}

      {!preview && !result && mode === "url" && multiUrl && (
        <div className="cf-card">
          <div className="cf-btn-row">
            <button
              className="cf-btn cf-btn-primary"
              disabled={bulkUrlLines.length === 0 || bulkRunning}
              onClick={handleBulkUrlImport}
            >
              {bulkRunning
                ? t("listsImportPage.multiUrlImporting", {
                    done: Object.values(bulkState).filter((s) => s === "done" || s === "error").length,
                    total: bulkUrlLines.length,
                  })
                : t("listsImportPage.multiUrlImport", { count: bulkUrlLines.length })}
            </button>
          </div>

          {bulkUrlLines.length > 0 && Object.keys(bulkState).length > 0 && (
            <div className="cf-table-wrap" style={{ marginTop: 16 }}>
              <table className="cf-table">
                <thead>
                  <tr>
                    <th>{t("comparisonsPage.columns.name")}</th>
                    <th>{t("importPage.columns.status")}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {bulkUrlLines.map((line, i) => {
                    const state = bulkState[i] ?? "idle";
                    const outcome = bulkResults[i];
                    return (
                      <tr key={i}>
                        <td>{outcome && "name" in outcome ? outcome.name : line}</td>
                        <td>
                          {state === "importing" && t("common.loading")}
                          {state === "done" && <span className="cf-badge cf-badge-ok">{t("importPage.status.ok")}</span>}
                          {state === "error" && (
                            <span
                              className="cf-badge cf-badge-error"
                              title={outcome && "error" in outcome ? outcome.error : ""}
                            >
                              {t("discoverPage.importFailed")}
                            </span>
                          )}
                        </td>
                        <td>
                          {state === "done" && outcome && "listId" in outcome && (
                            <Link className="cf-btn" to={`/lists/${outcome.listId}`}>
                              {t("listsImportPage.viewList")}
                            </Link>
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

          {preview.error_rows > 0 && (
            <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "center" }}>
              <input
                id="li-skip-bad-rows"
                type="checkbox"
                checked={skipBadRows}
                onChange={(e) => setSkipBadRows(e.target.checked)}
              />
              <label htmlFor="li-skip-bad-rows">
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

          <div className="cf-table-wrap" style={{ marginTop: 20 }}>
            <table className="cf-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{t("importPage.columns.status")}</th>
                  <th>{t("importPage.columns.name")}</th>
                  <th>{t("importPage.columns.quantity")}</th>
                  <th>{t("listsImportPage.columns.section")}</th>
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
                    <td>{(row.mapped_data?.section as string | undefined) ?? "—"}</td>
                    <td>{row.error_reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
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
            {resultListId && (
              <Link className="cf-btn" to={`/lists/${resultListId}`}>
                {t("listsImportPage.viewList")}
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
