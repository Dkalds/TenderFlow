/**
 * Exportación a CSV de los resultados que ya están en pantalla.
 *
 * No pasa por `/exports/download`: el CSV se arma aquí con lo que la vista
 * tiene, así que la descarga solo se mide si se emite por `descargarBlob`.
 */

import { descargarBlob } from "@/lib/export";
import type { SearchResult } from "./types";

const HEADERS = [
  "id_externo",
  "titulo",
  "organo",
  "ccaa",
  "estado",
  "fecha_limite",
  "importe",
  "coincide_en",
  "source",
];

function csvQuote(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

export function exportCSV(results: SearchResult[], source: string | null) {
  const rows = results.map((r) =>
    [
      csvQuote(r.id_externo),
      csvQuote(r.titulo ?? ""),
      csvQuote(r.organo_contratacion ?? ""),
      csvQuote(r.ccaa ?? ""),
      r.estado ?? "",
      r.fecha_limite ?? "",
      r.importe ?? "",
      // Dónde casa: «anuncio», «pliego» o los dos. Sustituye a la columna
      // `score`, que era un porcentaje relativo al primer resultado y se leía
      // como una relevancia que no era.
      r.coincide_en.join("+"),
      // La fuente es de la respuesta, no del resultado: llega una vez por
      // búsqueda.
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
