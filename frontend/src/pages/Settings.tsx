import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, apiPutJson, ApiError } from "../api/client";
import type { ComparisonMode } from "../types/comparison";
import type { CardNameLanguage, UserSettings, UserSettingsUpdate } from "../types/settings";

const AUTO_VALUE = "auto";

export default function Settings() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<UserSettings>("/settings")
      .then(setSettings)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  async function save(update: UserSettingsUpdate) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const response = await apiPutJson<UserSettings>("/settings", update);
      setSettings(response);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h2>{t("nav.settings")}</h2>
      {error && <div className="cf-alert cf-alert-error">{error}</div>}
      {saved && !error && <div className="cf-alert cf-alert-success">{t("settingsPage.saved")}</div>}
      {!settings && !error && <p>{t("common.loading")}</p>}

      {settings && (
        <div className="cf-card">
          <div className="cf-form-row">
            <label htmlFor="settings-mode">{t("settingsPage.defaultComparisonMode")}</label>
            <select
              id="settings-mode"
              className="cf-select"
              value={settings.default_comparison_mode}
              disabled={busy}
              onChange={(e) => save({ default_comparison_mode: e.target.value as ComparisonMode })}
            >
              <option value="oracle">{t("comparisonsPage.modes.oracle")}</option>
              <option value="printing">{t("comparisonsPage.modes.printing")}</option>
            </select>
          </div>

          <div className="cf-form-row">
            <label htmlFor="settings-currency">{t("settingsPage.preferredCurrency")}</label>
            <input
              id="settings-currency"
              className="cf-input"
              value={settings.preferred_currency}
              disabled={busy}
              maxLength={8}
              style={{ maxWidth: 120 }}
              onChange={(e) => setSettings({ ...settings, preferred_currency: e.target.value.toUpperCase() })}
              onBlur={(e) => save({ preferred_currency: e.target.value })}
            />
            <p style={{ fontSize: 12, color: "var(--cf-muted)", margin: 0 }}>
              {t("settingsPage.currencyHint")}
            </p>
          </div>

          <div className="cf-form-row">
            <label htmlFor="settings-card-name-language">{t("settingsPage.cardNameLanguage")}</label>
            <select
              id="settings-card-name-language"
              className="cf-select"
              value={settings.card_name_language ?? AUTO_VALUE}
              disabled={busy}
              onChange={(e) => {
                const value = e.target.value;
                save({ card_name_language: value === AUTO_VALUE ? null : (value as CardNameLanguage) });
              }}
            >
              <option value={AUTO_VALUE}>{t("settingsPage.cardNameLanguageAuto")}</option>
              <option value="de">{t("settingsPage.cardNameLanguages.de")}</option>
              <option value="en">{t("settingsPage.cardNameLanguages.en")}</option>
            </select>
            <p style={{ fontSize: 12, color: "var(--cf-muted)", margin: 0 }}>
              {t("settingsPage.cardNameLanguageHint")}
            </p>
          </div>

          <div className="cf-form-row">
            <label htmlFor="settings-grafana-embed">{t("settingsPage.grafanaEmbedUrl")}</label>
            <input
              id="settings-grafana-embed"
              className="cf-input"
              value={settings.grafana_embed_url ?? ""}
              disabled={busy}
              placeholder="http://<host>:3000/public-dashboards/..."
              onChange={(e) => setSettings({ ...settings, grafana_embed_url: e.target.value })}
              onBlur={(e) => save({ grafana_embed_url: e.target.value.trim() || null })}
            />
            <p style={{ fontSize: 12, color: "var(--cf-muted)", margin: 0 }}>
              {t("settingsPage.grafanaEmbedUrlHint")}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
