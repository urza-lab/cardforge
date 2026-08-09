Synthetic example import files land here starting in Phase 2 (a sample
ManaBox CSV export, a generic CSV, a text decklist, and a JSON cube list) —
used by both the test suite and as ready-to-try files for the Import pages.
No real/private collection data is ever committed here.

- `manabox_collection.csv` — ManaBox export format (see IMPORT_FORMATS.md).
- `generic_collection.csv` — arbitrary headers (`Card`/`Edition`/`Qty`/...),
  demonstrates auto-detected column mapping and an ignored extra column.
- `collection_list.txt` — text list, one card per line.
- `collection.json` — structured JSON collection.

All four parse cleanly with zero error rows — deliberately, so they're
reliable "upload this and see it work" demos and reusable pytest fixtures.
Parser error-row handling is covered by inline cases in the test suite
instead of by broken example files.
