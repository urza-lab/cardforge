export type PriceProvider = "scryfall" | "mtgjson" | "manual";
export type MtgjsonSyncStatus = "NOT_STARTED" | "FETCHING" | "CURRENT" | "FAILED";

export interface MtgjsonSyncStatusRead {
  provider: string;
  status: MtgjsonSyncStatus;
  started_at: string | null;
  finished_at: string | null;
  price_count: number;
  error_message: string | null;
}

export interface PriceProfile {
  id: number;
  name: string;
  currency: string;
  provider_priority: PriceProvider[];
  prefer_foil: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface PriceObservation {
  scryfall_card_id: string;
  provider: PriceProvider;
  currency: string;
  foil: boolean;
  price: string;
  observed_at: string;
}

export interface CardPrice {
  scryfall_card_id: string;
  currency: string;
  foil: boolean;
  price: string | null;
  provider: PriceProvider | null;
}

export interface PricedMissingCard {
  name: string;
  oracle_id: string | null;
  missing_quantity: number;
  unit_price: string | null;
  provider: PriceProvider | null;
}

export interface BudgetLine {
  name: string;
  oracle_id: string | null;
  unit_price: string;
  provider: PriceProvider;
  missing_quantity: number;
  affordable_quantity: number;
  line_total: string;
}

export interface BudgetResult {
  currency: string;
  budget: string;
  lines: BudgetLine[];
  total_spent: string;
  remaining_budget: string;
  fully_covered: boolean;
  unpriced: PricedMissingCard[];
}
