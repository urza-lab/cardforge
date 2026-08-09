import { useTranslation } from "react-i18next";

export default function Collection() {
  const { t } = useTranslation();
  return (
    <div>
      <h2>{t("nav.collection")}</h2>
      <div className="cf-card">
        <p>{t("common.comingSoon")}</p>
      </div>
    </div>
  );
}
