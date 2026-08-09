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
- Surfaces popularity/rating/power/salt signals for decks and cubes, where a
  source provides them.

## Why no AI

This is a deterministic bookkeeping problem (set arithmetic over card
quantities and prices), not a language problem. Keeping the whole pipeline
free of LLM calls means: no API keys to manage, no non-reproducible outputs,
no per-request cost, and a tool that keeps working identically five years
from now. See the project's design principles in `ARCHITECTURE.md`.

## Status

This repository is being built in phases (see `ARCHITECTURE.md` for the
phase plan). **Phases 1–3 are complete**: the Docker Compose stack,
persistent secrets, FastAPI health checks, and the React/TypeScript shell
(English/German UI) are up and testable; collection import — ManaBox CSV,
generic CSV, text lists, and JSON, each with a preview/confirm/abort flow
and per-row error reporting — is implemented end to end (see
`IMPORT_FORMATS.md`); and a local Scryfall card-data mirror, automatic
collection resolution against it, and both comparison modes (any printing /
exact printing) are live on the Comparisons page — paste or upload a
decklist and see what's buildable from your collection today. Later phases
(deck/cube pages, pricing, refresh system, dashboards) land incrementally on
top of this foundation.

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
| `BACKUP_RESTORE.md` | Backing up and restoring Postgres + secrets |

## License

GPL-3.0-or-later — see `LICENSE`. CardForge uses card data from Scryfall and
(optionally) MTGJSON; see `SOURCE_ADAPTERS.md` for attribution requirements.
Wizards of the Coast, Magic: The Gathering, and card names/images are
property of Wizards of the Coast LLC. CardForge is unofficial fan-made
software and is not produced, endorsed, supported, or affiliated with
Wizards of the Coast.
