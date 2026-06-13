/**
 * Versioned, safe localStorage helpers.
 *
 * - Keys are namespaced and version-prefixed (`lsap:v1:<key>`) so a schema bump
 *   invalidates stale data instead of crashing on parse.
 * - Every access is wrapped in try/catch: SSR (no `window`), private-mode quota
 *   errors, and malformed JSON all degrade gracefully to the fallback.
 */

const PREFIX = "lsap:v1:";

function fullKey(key: string): string {
  return `${PREFIX}${key}`;
}

/** Read and JSON-parse a value, returning `fallback` on any failure. */
export function getJSON<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(fullKey(key));
    if (raw == null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/** JSON-serialize and persist a value. Returns `false` if it could not be saved. */
export function setJSON(key: string, value: unknown): boolean {
  if (typeof window === "undefined") return false;
  try {
    window.localStorage.setItem(fullKey(key), JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

/** Remove a stored value. */
export function remove(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(fullKey(key));
  } catch {
    /* ignore */
  }
}
