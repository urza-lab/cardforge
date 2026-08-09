import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet } from "../api/client";
import type { ReadinessResponse } from "../types/health";

export default function SystemStatus() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<ReadinessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    </div>
  );
}
