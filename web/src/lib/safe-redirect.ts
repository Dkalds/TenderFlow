/** Resolve an untrusted return path without ever leaving this application. */
const FALLBACK_PATH = "/resumen";
const APPLICATION_ORIGIN = "https://tenderflow.invalid";

export function safeRedirectPath(candidate: string | null | undefined): string {
  if (
    !candidate ||
    candidate.length > 2_048 ||
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\") ||
    candidate.includes("\0")
  ) {
    return FALLBACK_PATH;
  }

  try {
    const parsed = new URL(candidate, APPLICATION_ORIGIN);
    if (parsed.origin !== APPLICATION_ORIGIN) {
      return FALLBACK_PATH;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return FALLBACK_PATH;
  }
}
