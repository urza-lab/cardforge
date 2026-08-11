export type EdhrecSyncStatus = "NOT_STARTED" | "FETCHING" | "CURRENT" | "FAILED";

export interface EdhrecSyncStatusRead {
  status: EdhrecSyncStatus;
  started_at: string | null;
  finished_at: string | null;
  deck_count: number;
  error_message: string | null;
}

export interface SynthesizedDeck {
  id: number;
  commander_slug: string;
  commander_name: string;
  rank: number;
  num_decks: number;
  color_identity: string[] | null;
  card_count: number;
  deck_text: string;
  source_url: string;
  synced_at: string;
}
