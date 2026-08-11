# CardForge — Deck & Cube Finder

CardForge compares your own Magic: The Gathering collection against Commander
decklists and cubes to show what's already buildable, what's missing, what a
few smart purchases would unlock, and what everything would cost — without
any AI/LLM involved anywhere in the pipeline. Every import, comparison,
pricing and refresh step is deterministic and reproducible.

## What it does

- Shows which decks/cubes are fully buildable from your collection today.
- Calculates exactly which cards and how many copies are missing.
- Finds the lists buildable with the fewest additional purchases, or within
  a budget.
- Ranks potential purchases by how much additional buildability they unlock
  ("collection leverage").
- Tracks coverage %, estimated remaining cost, and the age of every piece of
  external data (card data, prices, decklists) so you always know how stale
  something is.
- A native dashboard shows collection/deck stats at a glance, plus an
  optional real Grafana + Prometheus setup for deeper metrics history.
- Browse real popular Commander decks (ranked by Moxfield's and Archidekt's
  own view/like counts, filterable by color identity and — where set — WotC's
  official Commander Bracket) and import one — or several at once — against
  your collection with a click, instead of hunting down decklist URLs
  yourself.
- A separate EDHREC tab synthesizes an "average deck" for each of EDHREC's
  own real top 100 Commander picks, built from that commander's real
  most-played cards and typical card-type counts — clearly labeled as
  computed, not an actual decklist someone built, but still importable and
  comparable the same way.
- The optional Grafana stack can embed a "highest-coverage decks" panel
  directly on the Dashboard page (via Grafana's own Public Dashboard
  sharing, scoped to just that one panel) — see `ARCHITECTURE.md`.
- A separate Discover Cubes tab browses real popular cubes from CubeCobra
  (ranked by real likes) the same way Discover Decks does for Moxfield/
  Archidekt — one-click (or bulk) import, no URL hunting required.
- Scryfall's card mirror and MTGJSON's price cache can sync themselves
  automatically on a schedule (`CARDFORGE_PERIODIC_SYNC_ENABLED`, default
  on, every 24h) instead of needing a manual "Sync now" click.

## Why no AI

This is a deterministic bookkeeping problem (set arithmetic over card
quantities and prices), not a language problem. Keeping the whole pipeline
free of LLM calls means: no API keys to manage, no non-reproducible outputs,
no per-request cost, and a tool that keeps working identically five years
from now. See the project's design principles in `ARCHITECTURE.md`.

## Status

This repository was built in phases (see `ARCHITECTURE.md` for the full
plan) — **all 7 phases are complete**: the Docker Compose stack, persistent
secrets, FastAPI health checks, and the React/TypeScript shell
(English/German UI) are up and testable; collection import — ManaBox CSV,
generic CSV, text lists, and JSON, each with a preview/confirm/abort flow
and per-row error reporting — is implemented end to end (see
`IMPORT_FORMATS.md`); a local Scryfall card-data mirror (all languages),
automatic collection resolution against it, and both comparison modes (any
printing / exact printing) are live on the Comparisons page; and decks/cubes
have manual text/JSON/CSV import as well as import straight from a public
Moxfield or Archidekt deck URL, with a refresh button (and an automatic
background staleness sweep) to re-sync a URL-sourced list against changes
made at the source. Detail pages show a live buildability comparison, CSV
export, and a cross-list shopping list. Each card's name displays in
whatever language your import recorded for it by default, or a single
forced language (German/English) from Settings. Real market prices (from
Scryfall and MTGJSON — the latter also carries real Cardmarket EUR retail
data) plus your own manual overrides feed configurable price profiles, and
comparisons/shopping lists can be filtered by budget to see exactly what a
fixed amount of money would buy toward completing a deck or cube — see
`PRICING.md`. A native Dashboard page shows collection/deck stats and a
"what to buy next" collection-leverage ranking (which missing card would
complete the most decks/cubes), and an optional Grafana + Prometheus stack
(`docker compose --profile observability up -d`, off by default — set
`COMPOSE_PROFILES=observability` in `.env` to start it automatically on
every `docker compose up` instead) reads real metrics from the backend's
`/metrics` endpoint — see `ARCHITECTURE.md` "Documented default decisions"
for how leverage is computed and what the exporter reports.

## Quick start

See `QUICKSTART.md`.

```bash
cp .env.example .env
docker compose up -d --build
# open http://<host>:666
```

## Documentation

| Doc | Covers |
|---|---|
| `QUICKSTART.md` | Fastest path to a running instance |
| `DEVELOPMENT.md` | Local dev setup, hot reload, running tests |
| `ARCHITECTURE.md` | Design principles, phase plan, module boundaries |
| `SECURITY.md` | Auth model, persistent secrets, SSRF protections |
| `SOURCE_ADAPTERS.md` | How Scryfall/MTGJSON/Moxfield/Archidekt adapters work |
| `IMPORT_FORMATS.md` | ManaBox CSV, generic CSV, text list, JSON import formats |
| `PRICING.md` | Price cache, providers, price profiles, budget filter |
| `BACKUP_RESTORE.md` | Backing up and restoring Postgres + secrets |

## License

GPL-3.0-or-later — see `LICENSE`. CardForge uses card data from Scryfall and
(optionally) MTGJSON; see `SOURCE_ADAPTERS.md` for attribution requirements.
Wizards of the Coast, Magic: The Gathering, and card names/images are
property of Wizards of the Coast LLC. CardForge is unofficial fan-made
software and is not produced, endorsed, supported, or affiliated with
Wizards of the Coast.
