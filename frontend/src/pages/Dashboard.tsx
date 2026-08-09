import { useTranslation } from "react-i18next";

export default function Dashboard() {
  const { t } = useTranslation();
  return (
    <div>
      <h2>{t("nav.dashboard")}</h2>
      <div className="cf-card">
        <p>{t("common.comingSoon")}</p>
      </div>
    </div>
  );
}
