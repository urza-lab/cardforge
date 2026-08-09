import { useTranslation } from "react-i18next";

export default function ListsImport() {
  const { t } = useTranslation();
  return (
    <div>
      <h2>{t("nav.listsImport")}</h2>
      <div className="cf-card">
        <p>{t("common.comingSoon")}</p>
      </div>
    </div>
  );
}
