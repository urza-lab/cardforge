import { useTranslation } from "react-i18next";

export default function Comparisons() {
  const { t } = useTranslation();
  return (
    <div>
      <h2>{t("nav.comparisons")}</h2>
      <div className="cf-card">
        <p>{t("common.comingSoon")}</p>
      </div>
    </div>
  );
}
