import { useTranslation } from "react-i18next";

export default function Prices() {
  const { t } = useTranslation();
  return (
    <div>
      <h2>{t("nav.prices")}</h2>
      <div className="cf-card">
        <p>{t("common.comingSoon")}</p>
      </div>
    </div>
  );
}
