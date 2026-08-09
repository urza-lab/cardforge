import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, apiPostJson, ApiError } from "../api/client";
import type { ReadinessResponse } from "../types/health";
import type { ScryfallSyncStatus } from "../types/scryfall";

const POLL_INTERVAL_MS = 3000;

export default function SystemStatus() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<ReadinessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [scryfall, setScryfall] = useState<ScryfallSyncStatus | null>(null);
  const [scryfallError, setScryfallError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiGet<ReadinessResponse>("/health/ready")
      .then((data) => {
        if (!cancelled) setStatus(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const fetchScryfallStatus = useCallback(() => {
    apiGet<ScryfallSyncStatus>("/scryfall/status")
      .then(setScryfall)
      .catch((err: unknown) => setScryfallError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  useEffect(() => {
    fetchScryfallStatus();
  }, [fetchScryfallStatus]);

  useEffect(() => {
    if (scryfall?.status !== "FETCHING") return;
    const id = setInterval(fetchScryfallStatus, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [scryfall?.status, fetchScryfallStatus]);

  async function handleSync() {
    setSyncing(true);
    setScryfallError(null);
    try {
      const resp = await apiPostJson<ScryfallSyncStatus>("/scryfall/sync", {});
      setScryfall(resp);
    } catch (err) {
      setScryfallError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }

  const scryfallBadgeClass =
    scryfall?.status === "CURRENT"
      ? "cf-badge cf-badge-ok"
      : scryfall?.status === "FAILED"
        ? "cf-badge cf-badge-error"
        : "cf-badge cf-badge-warn";

  return (
    <div>
      <h2>{t("health.title")}</h2>
      <div className="cf-card">
        {error && <p style={{ color: "#ff6b6b" }}>{error}</p>}
        {!error && !status && <p>{t("health.unknown")}</p>}
        {status &&
          Object.entries(status.checks).map(([name, check]) => (
            <div key={name} style={{ marginBottom: 8 }}>
              <span className="cf-badge">{name}</span>{" "}
              {check.ok ? t("health.ok") : `${t("health.degraded")} — ${check.error}`}
            </div>
          ))}
      </div>

      <div className="cf-card">
        <h3 style={{ marginTop: 0 }}>{t("health.scryfall.title")}</h3>
        {scryfallError && <div className="cf-alert cf-alert-error">{scryfallError}</div>}
        {!scryfallError && !scryfall && <p>{t("health.unknown")}</p>}
        {scryfall && (
          <>
            <div className="cf-stat-row">
              <div className="cf-stat">
                <span className={scryfallBadgeClass}>{t(`health.scryfall.status.${scryfall.status}`)}</span>
              </div>
              <div className="cf-stat">
                <div className="cf-stat-value">{scryfall.card_count.toLocaleString()}</div>
                <div className="cf-stat-label">{t("health.scryfall.cardCount")}</div>
              </div>
            </div>
            {scryfall.source_updated_at && (
              <p>
                {t("health.scryfall.dataFrom")}{" "}
                {new Date(scryfall.source_updated_at).toLocaleString()}
              </p>
            )}
            {scryfall.status === "FAILED" && scryfall.error_message && (
              <div className="cf-alert cf-alert-error">{scryfall.error_message}</div>
            )}
            <div className="cf-btn-row">
              <button
                className="cf-btn cf-btn-primary"
                disabled={syncing || scryfall.status === "FETCHING"}
                onClick={handleSync}
              >
                {scryfall.status === "FETCHING" ? t("health.scryfall.syncing") : t("health.scryfall.syncNow")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
