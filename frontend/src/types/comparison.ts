export type ComparisonMode = "oracle" | "printing";
export type DecklistSourceType = "text_list" | "json" | "generic_csv";

export interface MissingCard {
  name: string;
  oracle_id: string | null;
  required_quantity: number;
  owned_quantity: number;
  missing_quantity: number;
}

export interface ComparisonRowError {
  row_number: number;
  raw: Record<string, unknown>;
  error: string;
}

export interface ComparisonResponse {
  mode: ComparisonMode;
  total_required_cards: number;
  total_required_quantity: number;
  total_owned_quantity: number;
  coverage_percent: number;
  is_fully_buildable: boolean;
  missing: MissingCard[];
  row_errors: ComparisonRowError[];
}
