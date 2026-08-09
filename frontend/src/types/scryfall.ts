export type ScryfallSyncStatusValue = "NOT_STARTED" | "FETCHING" | "CURRENT" | "FAILED";

export interface ScryfallSyncStatus {
  status: ScryfallSyncStatusValue;
  bulk_data_type: string;
  source_updated_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  card_count: number;
  error_message: string | null;
}
