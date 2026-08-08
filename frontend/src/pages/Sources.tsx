import { useTranslation } from "react-i18next";

export default function Sources() {
  const { t } = useTranslation();
  return (
    <div>
      <h2>{t("nav.sources")}</h2>
      <div className="cf-card">
        <p>{t("common.comingSoon")}</p>
      </div>
    </div>
  );
}
