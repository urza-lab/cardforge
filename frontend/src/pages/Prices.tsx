import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { apiGet, apiPostJson, apiPutJson, ApiError } from "../api/client";
import type { MtgjsonSyncStatusRead, PriceProfile, PriceProvider } from "../types/pricing";

const POLL_INTERVAL_MS = 3000;
const ALL_PROVIDERS: PriceProvider[] = ["manual", "mtgjson", "scryfall"];

export default function Prices() {
  const { t } = useTranslation();

  const [mtgjson, setMtgjson] = useState<MtgjsonSyncStatusRead | null>(null);
  const [mtgjsonError, setMtgjsonError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const [profiles, setProfiles] = useState<PriceProfile[] | null>(null);
  const [profilesError, setProfilesError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newCurrency, setNewCurrency] = useState("USD");
  const [newProviders, setNewProviders] = useState<PriceProvider[]>(["manual", "mtgjson", "scryfall"]);
  const [creating, setCreating] = useState(false);

  const [manualCardId, setManualCardId] = useState("");
  const [manualCurrency, setManualCurrency] = useState("USD");
  const [manualFoil, setManualFoil] = useState(false);
  const [manualPrice, setManualPrice] = useState("");
  const [manualBusy, setManualBusy] = useState(false);
  const [manualResult, setManualResult] = useState<string | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);

  const fetchMtgjsonStatus = useCallback(() => {
    apiGet<MtgjsonSyncStatusRead>("/mtgjson/status")
      .then(setMtgjson)
      .catch((err: unknown) => setMtgjsonError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  const fetchProfiles = useCallback(() => {
    apiGet<PriceProfile[]>("/price-profiles")
      .then(setProfiles)
      .catch((err: unknown) => setProfilesError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  useEffect(fetchMtgjsonStatus, [fetchMtgjsonStatus]);
  useEffect(fetchProfiles, [fetchProfiles]);

  useEffect(() => {
    if (mtgjson?.status !== "FETCHING") return;
    const id = setInterval(fetchMtgjsonStatus, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [mtgjson?.status, fetchMtgjsonStatus]);

  async function handleSync() {
    setSyncing(true);
    setMtgjsonError(null);
    try {
      const resp = await apiPostJson<MtgjsonSyncStatusRead>("/mtgjson/sync", {});
      setMtgjson(resp);
    } catch (err) {
      setMtgjsonError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }

  function toggleProvider(list: PriceProvider[], set: (v: PriceProvider[]) => void, provider: PriceProvider) {
    set(list.includes(provider) ? list.filter((p) => p !== provider) : [...list, provider]);
  }

  async function handleCreateProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newName.trim() || newProviders.length === 0) return;
    setCreating(true);
    setProfilesError(null);
    try {
      await apiPostJson("/price-profiles", {
        name: newName.trim(),
        currency: newCurrency.trim().toUpperCase(),
        provider_priority: newProviders,
        prefer_foil: false,
      });
      setNewName("");
      fetchProfiles();
    } catch (err) {
      setProfilesError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }

  async function handleSetDefault(profile: PriceProfile) {
    try {
      await apiPutJson(`/price-profiles/${profile.id}`, { is_default: true });
      fetchProfiles();
    } catch (err) {
      setProfilesError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function handleDeleteProfile(profile: PriceProfile) {
    try {
      const resp = await fetch(`/api/price-profiles/${profile.id}`, { method: "DELETE" });
      if (!resp.ok) throw new ApiError(resp.status, `delete failed with ${resp.status}`);
      fetchProfiles();
    } catch (err) {
      setProfilesError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function handleSetManualPrice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!manualCardId.trim() || !manualPrice.trim()) return;
    setManualBusy(true);
    setManualError(null);
    setManualResult(null);
    try {
      await apiPostJson("/prices/manual", {
        scryfall_card_id: manualCardId.trim(),
        currency: manualCurrency.trim().toUpperCase(),
        foil: manualFoil,
        price: manualPrice.trim(),
      });
      setManualResult(t("pricesPage.manualSaved"));
      setManualPrice("");
    } catch (err) {
      setManualError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setManualBusy(false);
    }
  }

  const mtgjsonBadgeClass =
    mtgjson?.status === "CURRENT"
      ? "cf-badge cf-badge-ok"
      : mtgjson?.status === "FAILED"
        ? "cf-badge cf-badge-error"
        : "cf-badge cf-badge-warn";

  return (
    <div>
      <h2>{t("nav.prices")}</h2>

      <div className="cf-card">
        <h3 style={{ marginTop: 0 }}>{t("pricesPage.mtgjson.title")}</h3>
        {mtgjsonError && <div className="cf-alert cf-alert-error">{mtgjsonError}</div>}
        {!mtgjsonError && !mtgjson && <p>{t("common.loading")}</p>}
        {mtgjson && (
          <>
            <div className="cf-stat-row">
              <div className="cf-stat">
                <span className={mtgjsonBadgeClass}>{t(`pricesPage.mtgjson.status.${mtgjson.status}`)}</span>
              </div>
              <div className="cf-stat">
                <div className="cf-stat-value">{mtgjson.price_count.toLocaleString()}</div>
                <div className="cf-stat-label">{t("pricesPage.mtgjson.priceCount")}</div>
              </div>
            </div>
            {mtgjson.status === "FAILED" && mtgjson.error_message && (
              <div className="cf-alert cf-alert-error">{mtgjson.error_message}</div>
            )}
            <div className="cf-btn-row">
              <button
                className="cf-btn cf-btn-primary"
                disabled={syncing || mtgjson.status === "FETCHING"}
                onClick={handleSync}
              >
                {mtgjson.status === "FETCHING" ? t("pricesPage.mtgjson.syncing") : t("pricesPage.mtgjson.syncNow")}
              </button>
            </div>
          </>
        )}
      </div>

      <div className="cf-card">
        <h3 style={{ marginTop: 0 }}>{t("pricesPage.profiles.title")}</h3>
        {profilesError && <div className="cf-alert cf-alert-error">{profilesError}</div>}
        {!profiles && !profilesError && <p>{t("common.loading")}</p>}

        {profiles && profiles.length > 0 && (
          <div className="cf-table-wrap">
            <table className="cf-table">
              <thead>
                <tr>
                  <th>{t("pricesPage.profiles.columns.name")}</th>
                  <th>{t("pricesPage.profiles.columns.currency")}</th>
                  <th>{t("pricesPage.profiles.columns.providers")}</th>
                  <th>{t("pricesPage.profiles.columns.default")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {profiles.map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td>{p.currency}</td>
                    <td>{p.provider_priority.map((pr) => t(`pricesPage.providers.${pr}`)).join(" → ")}</td>
                    <td>{p.is_default ? <span className="cf-badge cf-badge-ok">{t("common.yes")}</span> : "—"}</td>
                    <td style={{ textAlign: "right" }}>
                      {!p.is_default && (
                        <button className="cf-btn" onClick={() => handleSetDefault(p)}>
                          {t("pricesPage.profiles.makeDefault")}
                        </button>
                      )}{" "}
                      <button className="cf-btn" onClick={() => handleDeleteProfile(p)}>
                        {t("pricesPage.profiles.delete")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <form onSubmit={handleCreateProfile} style={{ marginTop: 16 }}>
          <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10, flexWrap: "wrap" }}>
            <div>
              <label htmlFor="pp-name">{t("pricesPage.profiles.columns.name")}</label>
              <input id="pp-name" className="cf-input" value={newName} onChange={(e) => setNewName(e.target.value)} />
            </div>
            <div>
              <label htmlFor="pp-currency">{t("pricesPage.profiles.columns.currency")}</label>
              <input
                id="pp-currency"
                className="cf-input"
                style={{ width: 70 }}
                value={newCurrency}
                onChange={(e) => setNewCurrency(e.target.value)}
              />
            </div>
            <div>
              <span style={{ fontSize: 13, color: "var(--cf-muted)", display: "block" }}>
                {t("pricesPage.profiles.columns.providers")}
              </span>
              {ALL_PROVIDERS.map((provider) => (
                <label key={provider} style={{ marginRight: 10 }}>
                  <input
                    type="checkbox"
                    checked={newProviders.includes(provider)}
                    onChange={() => toggleProvider(newProviders, setNewProviders, provider)}
                  />{" "}
                  {t(`pricesPage.providers.${provider}`)}
                </label>
              ))}
            </div>
            <button type="submit" className="cf-btn cf-btn-primary" disabled={creating || !newName.trim()}>
              {t("pricesPage.profiles.create")}
            </button>
          </div>
        </form>
      </div>

      <div className="cf-card">
        <h3 style={{ marginTop: 0 }}>{t("pricesPage.manual.title")}</h3>
        <p style={{ color: "var(--cf-muted)", marginTop: 0 }}>{t("pricesPage.manual.hint")}</p>
        {manualError && <div className="cf-alert cf-alert-error">{manualError}</div>}
        {manualResult && <div className="cf-alert cf-alert-success">{manualResult}</div>}
        <form onSubmit={handleSetManualPrice}>
          <div className="cf-form-row" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10, flexWrap: "wrap" }}>
            <div>
              <label htmlFor="mp-card-id">{t("pricesPage.manual.scryfallId")}</label>
              <input
                id="mp-card-id"
                className="cf-input"
                style={{ width: 280 }}
                value={manualCardId}
                onChange={(e) => setManualCardId(e.target.value)}
                placeholder="e.g. 1f0d2e46-25e6-4415-8c00-53abaf7de520"
              />
            </div>
            <div>
              <label htmlFor="mp-currency">{t("pricesPage.profiles.columns.currency")}</label>
              <input
                id="mp-currency"
                className="cf-input"
                style={{ width: 70 }}
                value={manualCurrency}
                onChange={(e) => setManualCurrency(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="mp-price">{t("pricesPage.manual.price")}</label>
              <input
                id="mp-price"
                className="cf-input"
                style={{ width: 100 }}
                value={manualPrice}
                onChange={(e) => setManualPrice(e.target.value)}
              />
            </div>
            <label style={{ marginBottom: 8 }}>
              <input type="checkbox" checked={manualFoil} onChange={(e) => setManualFoil(e.target.checked)} />{" "}
              {t("collection.columns.foil")}
            </label>
            <button type="submit" className="cf-btn cf-btn-primary" disabled={manualBusy || !manualCardId.trim() || !manualPrice.trim()}>
              {t("pricesPage.manual.save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
