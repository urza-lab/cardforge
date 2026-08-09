export type ImportSourceType = "manabox_csv" | "generic_csv" | "text_list" | "json";
export type ImportStatus = "previewed" | "confirmed" | "partially_confirmed" | "aborted";
export type ImportRowStatus = "ok" | "error";

export interface ImportRow {
  row_number: number;
  raw_data: Record<string, unknown>;
  mapped_data: Record<string, unknown> | null;
  status: ImportRowStatus;
  error_reason: string | null;
}

export interface ImportSummary {
  id: number;
  collection_id: number;
  source_type: ImportSourceType;
  original_filename: string | null;
  status: ImportStatus;
  column_mapping: Record<string, string> | null;
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  imported_rows: number;
  duplicate_of_import_id: number | null;
  created_at: string;
  confirmed_at: string | null;
}

export interface ImportPreview extends ImportSummary {
  rows: ImportRow[];
  is_likely_duplicate: boolean;
}
