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
    const destino = `${parsed.pathname}${parsed.search}${parsed.hash}`;
    // El `//` inicial se rechaza arriba sobre el texto que llega, pero la
    // normalización de la URL lo puede fabricar después: `/.//evil.example` no
    // empieza por `//` y su pathname normalizado sí (`//evil.example`). Un
    // navegador lee eso como otro host, así que la regla se comprueba también
    // sobre lo que se devuelve.
    return destino.startsWith("//") ? FALLBACK_PATH : destino;
  } catch {
    return FALLBACK_PATH;
  }
}
