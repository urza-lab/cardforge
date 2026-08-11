export type PreconSyncStatus = "NOT_STARTED" | "FETCHING" | "CURRENT" | "FAILED";

export interface PreconSyncStatusRead {
  status: PreconSyncStatus;
  started_at: string | null;
  finished_at: string | null;
  deck_count: number;
  error_message: string | null;
}

export interface PreconDeck {
  id: number;
  file_name: string;
  name: string;
  commander_names: string[];
  release_date: string | null;
  source_url: string;
  card_count: number;
  deck_text: string;
  synced_at: string;
  coverage_percent: number;
  is_fully_buildable: boolean;
  missing_count: number;
}
