# PRICING

**Status: Phase 6, done.** Price cache, Scryfall + MTGJSON price providers,
manual price overrides, price profiles, and a budget filter are all live
and verified against real data — see CLAUDE.md's Status section for the
real sync numbers (298,285 MTGJSON price observations, 294,681 Scryfall
price observations, both against the real 532,469-printing Scryfall
mirror).

## Price cache, not price history

`price_observations` (`backend/app/models/pricing.py`) holds the **latest
known** price per `(scryfall_card_id, provider, currency, foil)` — not a
time series. Each provider's sync replaces its own rows wholesale (same
"delete then bulk insert" pattern as the Scryfall card mirror sync), so
`observed_at` means "confirmed still current as of this sync," not a point
in a longer price-history graph. A dedicated history table (for price
trend charts, say) is a real possible future feature, but nothing today
reads price trends over time — see ARCHITECTURE.md's general principle of
not building for hypothetical future requirements.

## Providers

| Provider | Real data source | Currencies | Sync |
|---|---|---|---|
| `scryfall` | Scryfall's own `prices` field, already present in the `all_cards` bulk file the card mirror sync downloads | USD, EUR | Piggybacks the existing Scryfall bulk sync (`POST /api/scryfall/sync`) — no extra download |
| `mtgjson` | MTGJSON's `AllPricesToday.json` (TCGplayer USD retail, Cardmarket EUR retail) | USD, EUR | `POST /api/mtgjson/sync`, its own FETCHING/CURRENT/FAILED state (`GET /api/mtgjson/status`) |
| `manual` | Whatever you enter | Any | `POST /api/prices/manual` / `DELETE /api/prices/manual` — no sync, direct entry |

### Scryfall

`app/source_adapters/scryfall.py`'s `run_bulk_sync` already downloads and
parses every card's full JSON to build the `scryfall_cards` mirror; each
card object already carries a `prices` field
(`usd`/`usd_foil`/`usd_etched`/`eur`/`eur_foil`/`eur_etched`/`tix`). Only
the four most broadly useful fields are mirrored (`usd`, `usd_foil`,
`eur`, `eur_foil`) — `etched` finishes and MTGO `tix` are niche enough to
skip rather than add two more currencies/finishes nothing reads yet.

### MTGJSON

MTGJSON's own card UUIDs are a **different ID space** than Scryfall's —
`app/source_adapters/mtgjson.py`'s `run_price_sync` downloads two real
files and joins them in memory:

- `AllIdentifiers.json.xz` (~110MB compressed / ~630MB decompressed) — a
  single JSON object (not line-delimited like Scryfall's bulk export, so
  it's parsed in one shot), used only for its
  `data[uuid].identifiers.scryfallId` field to build an mtgjson-uuid →
  scryfall-id map.
- `AllPricesToday.json` (~50MB) — today's snapshot only, no price history
  (matching `price_observations`' "latest value" shape). TCGplayer retail
  → USD, Cardmarket retail → EUR, both `normal`/`foil` finishes.

This is also the real technical source for CardForge's Cardmarket price
data — see SOURCE_ADAPTERS.md for why there's no separate direct
Cardmarket-API adapter (their API needs OAuth app registration/approval;
MTGJSON already relays real Cardmarket retail prices without that).

Only `scryfall_card_id`s already present in the local Scryfall mirror are
written (the FK requires it) — a printing MTGJSON prices but the mirror
doesn't know about yet is silently skipped, not an error.

**Known real-data quirks this had to handle** (found via live syncs, not
assumed — see CLAUDE.md gotchas):
- More than one MTGJSON uuid can map to the same `scryfallId` (distinct
  promo/variation entries MTGJSON tracks separately) — rows are
  deduplicated by `(card, provider, currency, foil)` before inserting
  (last-write-wins), not left to crash the whole sync on a unique-
  constraint violation.
- A Scryfall resync's price-extraction batch can reach its flush threshold
  before the corresponding card batch does (each card contributes up to 4
  price rows but only 1 card row) — the two are now flushed together,
  cards always first, so a price row's card always exists before the
  price row is inserted.

### Manual

A direct per-printing override (`POST /api/prices/manual` — scryfall
printing ID, currency, foil, price), stored in the same
`price_observations` table with `provider="manual"`. Upserted, not
duplicated, on repeat calls for the same `(card, currency, foil)`.

## Price profiles

A `PriceProfile` (`name`, `currency`, `provider_priority` — an ordered list
of provider names, `prefer_foil`, `is_default`) resolves one actual price
for a card: `app/services/pricing_service.resolve_price` walks
`provider_priority` in order and returns the first provider that has a
price for that card in the profile's currency/foil combination — never a
fabricated average or fallback to $0. A default profile
(`manual → mtgjson → scryfall`, USD, non-foil) is bootstrapped lazily on
first use, same pattern as the default `Collection`
(`GET /api/price-profiles/default`).

**Oracle-mode pricing uses the cheapest printing, not a specific one.**
Oracle-mode comparison's own philosophy is "any printing satisfies this
requirement" (see `app/comparison/engine.py`) — pricing follows the same
logic: `resolve_cheapest_price_for_oracle` checks every printing sharing an
`oracle_id` and keeps the lowest match, rather than whichever printing a
particular import happened to resolve to. Printing-mode pricing resolves
the exact printing instead, since only that one satisfies the requirement.

Pricing is **opt-in**, not computed on every comparison — `GET
/api/lists/{id}/comparison` and `GET /api/shopping-list` both accept an
optional `price_profile_id` query param; without it, `priced_missing` and
`budget` are both `null` in the response. This is deliberate: pricing a
missing-card list means one DB round trip per card (more for oracle mode,
which checks every printing sharing an oracle_id) — not something to pay on
every plain buildability check.

## Budget filter

`app/pricing/budget.py`'s `apply_budget` is a **pure function** (no DB
access, mirroring `app.comparison.engine`'s "plain data in, plain data
out" shape) over already-priced missing-card data: cheapest-unit-price-
first greedy allocation within a fixed budget, reporting exactly how many
copies of each missing card fit, the total spent, what's left over, and
which cards had no resolvable price at all (never silently treated as
free). This is **not** collection-leverage-aware (that's Phase 7's "which
purchases unlock the most buildability") — it only answers "what does a
fixed budget stretch to buy," sorted by price alone.

`GET /api/lists/{id}/comparison?price_profile_id=1&budget=50` (or the
equivalent on `/api/shopping-list` for a multi-list budget) returns a
`budget` object: `lines` (per-card allocation), `total_spent`,
`remaining_budget`, `fully_covered` (true only if every missing card was
both priced and fully affordable), and `unpriced` (cards a budget can't
account for because no provider had a price).

## Frontend

- **Prices page** (`/prices`): MTGJSON sync status/trigger (mirrors System
  Status's Scryfall block), price profile management (create, set default,
  delete), and a manual price-entry form.
- **List detail page**: a price-profile selector + optional budget input on
  the existing comparison card, showing per-missing-card unit prices and
  (if a budget was given) the affordability breakdown.
- Collection/list-wide total valuation (e.g. "your collection is worth
  $X") is **not implemented** — it would mean resolving a price for every
  item client-side (thousands of round trips for a large collection) with
  no batch-pricing endpoint built yet. Deferred rather than shipped as a
  slow/unbounded feature.
