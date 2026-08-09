# IMPORT_FORMATS

**Status:** parsers land in Phase 2 (collection: ManaBox/generic CSV, text,
JSON) and Phase 5 (deck/cube: text, CSV, JSON, public URLs). This document
specifies the target formats so importers can be built against a stable
spec.

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
condition, price). Unmapped columns are ignored.

## Text lists

One card per line, formats accepted:

```
4 Lightning Bolt
1 Sol Ring (C21) 263
Commander: Atraxa, Praetors' Voice
```

Supported line prefixes/sections for deck import (Phase 5):
`Commander:`, `Companion:`, `Sideboard:`, `Maybeboard:`, `Considering:` — any
line before the first section header is treated as mainboard.

## JSON

A structured list/collection export:

```json
{
  "name": "My Cube",
  "cards": [
    { "name": "Lightning Bolt", "set": "LEA", "collector_number": "161", "quantity": 1 }
  ]
}
```

Extra fields (`category`, `tags`, `foil`, `language`, `condition`) are
preserved when present and used where relevant (e.g. cube category
coverage, Phase 4).

## Duplicate import prevention

Every import is hashed (file content hash) and tagged with an idempotency
key. Re-uploading the same file is detected and the user is asked whether to
skip it or re-process it explicitly — it is never silently re-applied.

## Row-level handling

Every row that fails validation (unparseable quantity, unknown set code with
no fallback, etc.) is listed individually in the import preview with a
reason. You can either skip just the bad rows and import the rest, or abort
the whole import — nothing is partially applied without your explicit choice.
