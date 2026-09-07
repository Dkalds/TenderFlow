/**
 * Exportación a CSV de los resultados que ya están en pantalla.
 *
 * No pasa por `/exports/download`: el CSV se arma aquí con lo que la vista
 * tiene, así que la descarga solo se mide si se emite por `descargarBlob`.
 */

import { descargarBlob } from "@/lib/export";
import type { SearchResult } from "./types";

const HEADERS = ["id_externo", "titulo", "organo", "importe", "score", "source"];

function csvQuote(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

export function exportCSV(results: SearchResult[], source: string | null) {
  const rows = results.map((r) =>
    [
      r.id_externo ?? r.id ?? "",
      csvQuote(r.titulo ?? ""),
      csvQuote(r.organo_contratacion ?? r.organo ?? ""),
      r.importe ?? "",
      r.score != null ? r.score.toFixed(4) : "",
      // La fuente es de la respuesta, no del hit: el backend la devuelve una
      // vez por búsqueda. La columna se rellenaba con un campo por hit que la
      // API nunca ha devuelto, así que salía siempre vacía.
      source ?? "",
    ].join(","),
  );
  const csv = [HEADERS.join(","), ...rows].join("\n");
  descargarBlob(
    `investigador_resultados_${Date.now()}.csv`,
    new Blob([csv], { type: "text/csv;charset=utf-8;" }),
    "investigador",
  );
}
