export interface Collection {
  id: number;
  name: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface CollectionItem {
  id: number;
  card_name: string;
  set_code: string | null;
  set_name: string | null;
  collector_number: string | null;
  quantity: number;
  foil: boolean;
  language: string | null;
  condition: string | null;
  purchase_price: string | null;
  purchase_currency: string | null;
  scryfall_id: string | null;
  source_import_id: number | null;
  created_at: string;
  updated_at: string;
}
