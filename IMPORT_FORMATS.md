# IMPORT_FORMATS

**Status:** collection import (ManaBox CSV, generic CSV, text, JSON) landed
in Phase 2. Deck/cube manual import (text, JSON) landed in Phase 4 — see
ARCHITECTURE.md "Documented default decisions" for why that moved earlier
than the phase-plan table originally implied. Deck/cube **CSV** import and
the Moxfield/Archidekt **public URL** adapters landed in Phase 5.

All imports go through the same pipeline: file check → column/field
detection → preview with editable column mapping → row validation → summary
of successful/failed rows → explicit confirm (or skip-bad-rows / abort).
Nothing is written to the database until the user confirms the preview.

## ManaBox CSV

Column order is **not** assumed — columns are detected by header name
(case-insensitive, tolerant of common variants) and can be corrected
manually in the import preview. Recognized fields:

| Field | Example |
|---|---|
| Card name | `Lightning Bolt` |
| Set name | `Alpha` |
| Set code | `LEA` |
| Quantity | `4` |
| Foil | `foil` / `normal` |
| Collector / card number | `161` |
| Language | `EN` |
| Condition | `NM`, `LP`, `MP`, `HP`, `DMG` |
| Purchase price | `2.50` |
| Purchase currency | `CHF`, `EUR`, `USD` |
| Scryfall ID | `e3285e6b-3e79-4d7c-bf96-d920f973b122` |

If a `Scryfall ID` column is present, it takes priority for identifying the
exact printing; otherwise CardForge resolves `set code` + `collector number`
+ `name` against the local Scryfall printing database. This resolution runs
automatically right after a confirmed import (Phase 3, see
`app/services/scryfall_resolution.py`) — the parser itself stays
Scryfall-agnostic (see ARCHITECTURE.md's module boundaries: `parsers/` are
pure functions with no DB access).

## Generic CSV

Any CSV with at least a card-name column and a quantity column. The import
preview shows detected columns and lets you map arbitrary headers to
CardForge fields (name, set, collector number, quantity, foil, language,
condition, price). Unmapped columns are ignored. **Collection import only**
— it has no section/category/tags columns, so it can't carry a deck/cube's
shape; use the **deck/cube CSV** format below (or text/JSON) for those.

## Deck/cube CSV

A separate CSV shape for deck/cube import (`app/parsers/list_csv.py`,
`source_type: "csv"` on `POST /api/list-imports/preview`) — same tolerant
header-detection/column-mapping mechanics as Generic CSV above, but mapped
onto `CardListItem` fields instead of `CollectionItem`'s: no
condition/purchase price/currency (not list concepts), but `section`,
`category`, and `tags` columns instead, so a cube's category grouping or a
deck's sideboard survive a CSV round trip the way they already did for text
and JSON list import.

| Field | Example |
|---|---|
| Card name | `Sol Ring` |
| Set name / Set code | `Commander 2021` / `C21` |
| Collector number | `263` |
| Quantity | `1` |
| Foil | `foil` / blank |
| Language | `EN` |
| Scryfall ID | `1f0d2e46-25e6-4415-8c00-53abaf7de520` |
| Section | `commander` (blank defaults to `mainboard`, same values as text lists above) |
| Category | `Ramp` (free text) |
| Tags | `fast-mana,cheap` (comma-separated) |

## Text lists

One card per line. **Collection** text import (Phase 2,
`app/parsers/text_list.py`) accepts plain `<quantity> <name>` lines only —
section headers are a validation error there, since a collection has no
concept of "sideboard". **Deck/cube** text import (Phase 4,
`app/parsers/list_text.py`) additionally accepts section headers:

```
4 Lightning Bolt
1 Sol Ring (C21) 263
Commander: Atraxa, Praetors' Voice
Sideboard:
1 Rest in Peace
```

Supported section headers: `Commander:`, `Companion:`, `Sideboard:`,
`Maybeboard:`, `Considering:`. A header applies to every line after it until
the next header (so `Sideboard:` followed by several lines puts all of them
in the sideboard) — put mainboard cards first, unheaded, and put the special
sections at the end, matching the example above. A quantity prefix is
optional and defaults to 1 (`Commander: Atraxa, Praetors' Voice` needs no
`1`). Only `mainboard`/`commander`/`companion` count toward "is this list
buildable" (see `app/services/comparison_service.py`
`REQUIRED_LIST_SECTIONS`) — `sideboard`/`maybeboard`/`considering` are
informational only.

## JSON

A structured list/collection export, shared by collection and deck/cube
import (`app/parsers/json_list.py`):

```json
{
  "name": "My Cube",
  "cards": [
    { "name": "Lightning Bolt", "set": "LEA", "collector_number": "161", "quantity": 1 },
    { "name": "Sol Ring", "quantity": 1, "section": "commander", "category": "Ramp", "tags": ["fast-mana"] }
  ]
}
```

`section` (defaults to `mainboard` if absent, same values as text lists
above), `category` (free text, e.g. a cube's archetype/role grouping), and
`tags` (a list of strings, or a comma-separated string) are parsed and
stored for deck/cube import; collection import simply doesn't read them.

## Duplicate import prevention

Every import is hashed (file content hash) and tagged with an idempotency
key. Re-uploading the same file is detected and the user is asked whether to
skip it or re-process it explicitly — it is never silently re-applied.

## Row-level handling

Every row that fails validation (unparseable quantity, unknown set code with
no fallback, etc.) is listed individually in the import preview with a
reason. You can either skip just the bad rows and import the rest, or abort
the whole import — nothing is partially applied without your explicit choice.
