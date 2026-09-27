/**
 * Etiquetas visibles del campo `source` de POST /api/v1/search/semantic.
 *
 * Las claves son, exactamente, los tres valores que el backend puede devolver
 * (`SEARCH_SOURCES` en `api/routes/search.py`). Viven en su propio módulo por
 * dos razones: la página no es el sitio de un contrato, y
 * `tests/test_search_semantic_source.py` lee ESTE fichero para comprobar que
 * la UI no etiqueta una fuente que el backend no emite —ni deja sin etiquetar
 * una que sí— que es justo lo que había pasado con el deslizador «Alpha (FAISS
 * vs FTS5)»: pintaba un motor retirado.
 *
 * Las etiquetas hablan como quien busca: «Por significado y texto», no
 * «Semántica + texto (RRF)». El nombre del algoritmo no le dice nada a nadie
 * fuera del equipo.
 */
export const SOURCE_LABELS: Record<string, string> = {
  rrf: "Por significado y texto",
  fts: "Texto completo",
  like: "Coincidencia literal",
};

/**
 * Qué explica cada fuente, para que «Texto completo» no se lea como un fallo.
 */
export const SOURCE_HINTS: Record<string, string> = {
  rrf: "Combina las palabras exactas con el parecido de significado sobre los pliegos indexados; cuánto pesa cada lado lo fija «Tipo de coincidencia».",
  fts: "Sin pliegos indexados que combinar: resultados por palabras exactas. «Tipo de coincidencia» no interviene.",
  like: "La búsqueda por texto no encontró nada: resultados por coincidencia literal, sin orden de relevancia.",
};

/**
 * Etiqueta de una fuente. Un valor desconocido se devuelve tal cual en lugar
 * de ocultarse: si el backend gana un camino nuevo, la UI lo dice aunque no
 * sepa nombrarlo — mejor un nombre feo que una etiqueta falsa.
 */
export function sourceLabel(source: string | null | undefined): string | null {
  if (!source) return null;
  return SOURCE_LABELS[source] ?? source;
}

export function sourceHint(source: string | null | undefined): string | null {
  if (!source) return null;
  return SOURCE_HINTS[source] ?? null;
}
