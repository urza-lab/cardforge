import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";
import de from "./locales/de.json";
import en from "./locales/en.json";

// CardForge ships its own first-party translation files (en, de) under
// src/i18n/locales — there is no reliable external MTG-UI translation source
// to pull from, so strings are authored and maintained in this repo. Adding a
// language means dropping a new locales/<code>.json file here and listing it
// in SUPPORTED_LOCALES below.
export const SUPPORTED_LOCALES = [
  { code: "en", label: "English" },
  { code: "de", label: "Deutsch" },
];

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      de: { translation: de },
    },
    fallbackLng: "en",
    interpolation: { escapeValue: false },
  });

export default i18n;
