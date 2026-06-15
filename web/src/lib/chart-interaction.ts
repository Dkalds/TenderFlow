/**
 * Helpers for click-to-filter (cross-filter) interactions on Recharts charts.
 */

/** Add/remove a value from a multi-select filter array (toggle semantics). */
export function toggleValue(value: string, current: string[]): string[] {
  return current.includes(value)
    ? current.filter((v) => v !== value)
    : [...current, value];
}

/**
 * Extract a string field from a Recharts click-handler argument.
 * Recharts may pass the datum directly or wrapped as `{ payload: datum }`.
 */
export function chartClickField(arg: unknown, field: string): string | undefined {
  if (arg && typeof arg === "object") {
    const o = arg as Record<string, unknown>;
    const payload = o.payload as Record<string, unknown> | undefined;
    const value = payload?.[field] ?? o[field];
    return typeof value === "string" ? value : undefined;
  }
  return undefined;
}
