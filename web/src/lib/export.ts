/**
 * Export URL building + download triggering — shared by ExportPopover and the
 * command palette's "Acciones con filtros" group so both stay in sync with a
 * single source of truth for how export query params are assembled.
 */

import { dimensionesDeDescarga, registrarEvento } from "./analytics";

/**
 * Build a download URL for the given endpoint, combining the requested
 * format, the active filter params and any extra (page-specific) params as
 * query string parameters. Empty/nullish filter values are skipped.
 */
export function buildExportUrl(
  endpoint: string,
  format: "csv" | "xlsx",
  filterParams: Record<string, string>,
  extraParams?: Record<string, string>,
): string {
  const params = new URLSearchParams();
  params.set("format", format);

  if (filterParams) {
    for (const [key, value] of Object.entries(filterParams)) {
      if (value != null && value !== "") {
        params.set(key, String(value));
      }
    }
  }

  if (extraParams) {
    for (const [key, value] of Object.entries(extraParams)) {
      params.set(key, value);
    }
  }

  return `${endpoint}?${params.toString()}`;
}

/**
 * Trigger a browser download for `url` via a programmatic, invisible `<a>` click.
 *
 * Aquí se mide, y no en los dos llamadores, porque este es el embudo por el que
 * pasa toda descarga: instrumentar las llamadas dejaría fuera al tercero que
 * aparezca. De la URL sólo se conserva formato y recurso —la query lleva los
 * filtros escritos por el usuario y no sale de este proceso (ver
 * `dimensionesDeDescarga`).
 */
export function triggerDownload(url: string): void {
  registrarEvento("export_lanzado", dimensionesDeDescarga(url));
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
