import type { ComparisonMode } from "./comparison";

export type CardNameLanguage = "de" | "en";

export interface UserSettings {
  default_comparison_mode: ComparisonMode;
  preferred_currency: string;
  card_name_language: CardNameLanguage | null;
  grafana_embed_url: string | null;
  updated_at: string;
}

export interface UserSettingsUpdate {
  default_comparison_mode?: ComparisonMode;
  preferred_currency?: string;
  card_name_language?: CardNameLanguage | null;
  grafana_embed_url?: string | null;
}
