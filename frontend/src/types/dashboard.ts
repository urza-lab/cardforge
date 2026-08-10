export interface ListBuildability {
  list_id: number;
  name: string;
  list_type: "deck" | "cube";
  coverage_percent: number;
  is_fully_buildable: boolean;
}

export interface LeverageCandidate {
  name: string;
  oracle_id: string | null;
  scryfall_card_id: string | null;
  quantity_needed: number;
  lists_newly_buildable: number;
  total_coverage_gain: number;
}

export interface DashboardSummary {
  collection_distinct_items: number;
  collection_total_quantity: number;
  collection_resolved_count: number;
  list_count: number;
  lists_fully_buildable: number;
  average_coverage_percent: number;
  scryfall_sync_status: string;
  scryfall_card_count: number;
  scryfall_source_updated_at: string | null;
  mtgjson_sync_status: string;
  mtgjson_price_count: number;
  list_buildability: ListBuildability[];
  top_leverage: LeverageCandidate[];
}
