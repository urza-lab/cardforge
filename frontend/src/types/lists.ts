import type { MissingCard } from "./comparison";

export type ListType = "deck" | "cube";
export type ListSection = "mainboard" | "commander" | "companion" | "sideboard" | "maybeboard" | "considering";
export type ListImportSourceType = "text" | "json" | "csv" | "moxfield" | "archidekt";
export type ListImportStatus = "previewed" | "confirmed" | "partially_confirmed" | "aborted";
export type ListRefreshStatus = "FETCHING" | "CURRENT" | "FAILED" | "AUTH_REQUIRED";

export interface CardList {
  id: number;
  name: string;
  list_type: ListType;
  source_url: string | null;
  source_type: ListImportSourceType | null;
  refresh_status: ListRefreshStatus | null;
  refresh_error: string | null;
  last_refreshed_at: string | null;
  is_stale: boolean;
  created_at: string;
  updated_at: string;
}

export interface CardListItem {
  id: number;
  card_name: string;
  display_name: string;
  set_code: string | null;
  set_name: string | null;
  collector_number: string | null;
  quantity: number;
  section: ListSection;
  category: string | null;
  tags: string[] | null;
  foil: boolean;
  language: string | null;
  scryfall_id: string | null;
  resolved_oracle_id: string | null;
  resolved_scryfall_card_id: string | null;
  resolved_at: string | null;
  source_import_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface ListImportRow {
  row_number: number;
  raw_data: Record<string, unknown>;
  mapped_data: Record<string, unknown> | null;
  status: "ok" | "error";
  error_reason: string | null;
}

export interface ListImportSummary {
  id: number;
  list_id: number;
  source_type: ListImportSourceType;
  original_filename: string | null;
  source_url: string | null;
  status: ListImportStatus;
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  imported_rows: number;
  duplicate_of_import_id: number | null;
  created_at: string;
  confirmed_at: string | null;
}

export interface ListImportPreview extends ListImportSummary {
  rows: ListImportRow[];
  is_likely_duplicate: boolean;
}

export interface ListComparisonResponse {
  mode: "oracle" | "printing";
  total_required_cards: number;
  total_required_quantity: number;
  total_owned_quantity: number;
  coverage_percent: number;
  is_fully_buildable: boolean;
  missing: MissingCard[];
}
