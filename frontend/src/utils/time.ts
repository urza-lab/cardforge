// Backend datetime columns aren't stored with an explicit timezone (see
// CLAUDE.md) - Postgres silently drops the UTC marker on round-trip even
// though the value really is UTC, so the API returns timestamps with no
// "Z"/offset suffix (e.g. "2026-08-12T20:55:49"). `new Date(...)` on a
// string like that is parsed as *local* time by the browser, not UTC -
// confirmed live: it silently inflated a running-scrape's "elapsed" stat
// by exactly the user's local UTC offset. Treat any offset-less timestamp
// from the API as UTC explicitly instead of trusting the ambient parse.
export function parseUtcTimestamp(raw: string): number {
  const hasTimezone = /(Z|[+-]\d{2}:?\d{2})$/.test(raw);
  return new Date(hasTimezone ? raw : `${raw}Z`).getTime();
}
