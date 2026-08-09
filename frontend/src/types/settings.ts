import type { ComparisonMode } from "./comparison";

export interface UserSettings {
  default_comparison_mode: ComparisonMode;
  preferred_currency: string;
  updated_at: string;
}

export interface UserSettingsUpdate {
  default_comparison_mode?: ComparisonMode;
  preferred_currency?: string;
}
