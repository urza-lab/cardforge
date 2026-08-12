export type CubeDiscoverySyncStatus = "NOT_STARTED" | "FETCHING" | "CURRENT" | "FAILED";

export interface CubeDiscoverySyncStatusRead {
  status: CubeDiscoverySyncStatus;
  started_at: string | null;
  finished_at: string | null;
  cube_count: number;
  error_message: string | null;
}

export interface PopularCube {
  id: number;
  name: string;
  owner_username: string | null;
  source_url: string;
  card_count: number;
  like_count: number;
  tags: string[] | null;
  num_decks: number | null;
  date_last_updated: string | null;
  synced_at: string;
  imported_list_id: number | null;
  import_error: string | null;
  import_attempted_at: string | null;
}
