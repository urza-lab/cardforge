import { useMemo, useState } from "react";

export const ROW_LIMIT_OPTIONS = [25, 50, 100, 200] as const;
export type RowLimit = (typeof ROW_LIMIT_OPTIONS)[number] | "all";

/** Client-side display cap for tables that can grow into the hundreds or
 * thousands of rows (a real collection's decks/cubes, "what to buy next"
 * candidates) - user-requested after a real 1,400+-list collection made an
 * unbounded table a real render-performance problem, not a hypothetical
 * one. Defaults to the smallest option so a first load never renders more
 * than necessary; "all" is still one click away.
 */
export function useRowLimit(initial: RowLimit = 25) {
  const [limit, setLimit] = useState<RowLimit>(initial);
  return { limit, setLimit };
}

/** Slice `rows` down to `limit`, memoized - "all" passes them through unchanged. */
export function useLimited<T>(rows: T[], limit: RowLimit): T[] {
  return useMemo(() => (limit === "all" ? rows : rows.slice(0, limit)), [rows, limit]);
}
