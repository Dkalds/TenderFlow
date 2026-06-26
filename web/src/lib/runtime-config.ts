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
