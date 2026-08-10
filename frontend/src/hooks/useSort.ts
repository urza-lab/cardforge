import { useMemo, useState } from "react";

export type SortDirection = "asc" | "desc";

/** Lightweight client-side sort for a table — no component library needed
 * for the "interactive tables" requirement (see ARCHITECTURE.md "no heavy
 * component framework"). Rows are re-sorted from the original array each
 * render (cheap for the row counts this app deals with: hundreds, not
 * millions), so callers don't need to manage sorted state themselves.
 */
export function useSort<T>(rows: T[], initialKey: keyof T, initialDirection: SortDirection = "asc") {
  const [sortKey, setSortKey] = useState<keyof T>(initialKey);
  const [direction, setDirection] = useState<SortDirection>(initialDirection);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      let cmp: number;
      if (typeof av === "number" && typeof bv === "number") {
        cmp = av - bv;
      } else {
        cmp = String(av ?? "").localeCompare(String(bv ?? ""));
      }
      return direction === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, direction]);

  function toggleSort(key: keyof T) {
    if (key === sortKey) {
      setDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setDirection("asc");
    }
  }

  return { sorted, sortKey, direction, toggleSort };
}
