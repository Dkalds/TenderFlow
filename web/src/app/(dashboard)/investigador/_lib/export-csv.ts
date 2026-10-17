/**
 * Exportación a CSV de los resultados que ya están en pantalla.
 *
 * No pasa por `/exports/download`: el CSV se arma aquí con lo que la vista
 * tiene, así que la descarga solo se mide si se emite por `descargarBlob`. Las
 * celdas van por `csvBlob` (`@/lib/export`), como el resto de CSV compuestos en
 * el cliente: con BOM para que Excel lea las tildes, y un título que empiece
 * por `=` no se ejecuta como fórmula.
 */

import { csvBlob, descargarBlob } from "@/lib/export";
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

export function exportCSV(results: SearchResult[], source: string | null) {
  const rows = results.map((r) => [
    r.id_externo,
    r.titulo,
    r.organo_contratacion,
    r.ccaa,
    r.estado,
    r.fecha_limite,
    r.importe,
    // Dónde casa: «anuncio», «pliego», «significado» o varios. Sustituye a la
    // columna `score`, que era un porcentaje relativo al primer resultado y se
    // leía como una relevancia que no era.
    r.coincide_en.join("+"),
    // La fuente es de la respuesta, no del resultado: llega una vez por
    // búsqueda.
    source,
  ]);
  descargarBlob(`investigador_resultados_${Date.now()}.csv`, csvBlob([HEADERS, ...rows]), "investigador");
}
