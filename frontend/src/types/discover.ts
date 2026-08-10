export type DeckDiscoverySyncStatus = "NOT_STARTED" | "FETCHING" | "CURRENT" | "FAILED";

export interface DeckDiscoverySyncStatusRead {
  status: DeckDiscoverySyncStatus;
  started_at: string | null;
  finished_at: string | null;
  deck_count: number;
  error_message: string | null;
}

export interface PopularDeck {
  id: number;
  source: string;
  name: string;
  author: string | null;
  source_url: string;
  format: string;
  view_count: number;
  like_count: number;
  color_identity: string[] | null;
  synced_at: string;
}
