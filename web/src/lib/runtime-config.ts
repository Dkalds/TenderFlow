/**
 * Runtime configuration that comes from the environment, never hardcoded.
 *
 * Per ADR-014 (integridad analítica del frontend): no hardcoded URLs in
 * rendered data. The Grafana URL must come from `NEXT_PUBLIC_GRAFANA_URL`;
 * if it is not configured we hide the link instead of pointing the user at a
 * broken `http://localhost:3001`.
 */

/**
 * The configured Grafana URL, or `null` when not set (or blank). Callers must
 * hide the Grafana link when this is `null`.
 */
export function getGrafanaUrl(): string | null {
  const url = process.env.NEXT_PUBLIC_GRAFANA_URL?.trim();
  return url ? url : null;
}

/**
 * Origen de la API para llamadas desde el servidor.
 *
 * `next.config.ts` reescribe `/api/*` hacia el backend, pero esos rewrites los
 * aplica el proxy a las peticiones que **entran** desde el navegador: un
 * `fetch` que hace el propio servidor de Next no pasa por ahí. Hay que apuntar
 * al backend directamente.
 */
export function origenApi(): string {
  // fdi-allow:localhost-url — fallback de desarrollo para fetch SSR; no es dato renderizado.
  return process.env.API_BASE_URL ?? "http://localhost:8080";
}
