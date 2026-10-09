/**
 * Etiquetas visibles del campo `source` de POST /api/v1/search/semantic.
 *
 * Las claves son, exactamente, los valores que la búsqueda puede devolver
 * (`SEARCH_SOURCES` en `api/routes/search.py`). Viven en su propio módulo por
 * dos razones: la página no es el sitio de un contrato, y
 * `tests/test_search_semantic_source.py` lee ESTE fichero para comprobar que
 * la UI no etiqueta una fuente que la búsqueda no emite —ni deja sin etiquetar
 * una que sí— que es justo lo que había pasado con el deslizador «Alpha (FAISS
 * vs FTS5)»: nombraba un motor retirado.
 *
 * Las etiquetas hablan como quien busca: «Por significado y texto», no
 * «Semántica + texto (RRF)». El nombre del algoritmo no le dice nada a nadie
 * fuera del equipo.
 */
export const SOURCE_LABELS: Record<string, string> = {
  rrf: "Por significado y texto",
  fts: "Por texto",
  like: "Coincidencia literal",
  filtros: "Solo filtros",
};

/**
 * Qué explica cada fuente. Dicen lo que se hizo, no lo que falta: «Por texto»
 * no es un fallo de otra cosa, es la búsqueda.
 */
export const SOURCE_HINTS: Record<string, string> = {
  rrf: "Combina las palabras de tu consulta con el parecido de significado sobre los pliegos; cuánto pesa cada lado lo fija «Tipo de coincidencia».",
  fts: "Busca las palabras de tu consulta en los anuncios y dentro de los pliegos. Primero van los que las contienen todas.",
  like: "Ninguna palabra de tu consulta aparece como tal: estos resultados contienen parte de su texto. Sin orden de relevancia, los más recientes primero.",
  filtros: "Tu consulta no trae palabras que buscar: esto es lo más reciente dentro de los filtros.",
};

/**
 * Etiqueta de una fuente. Un valor desconocido se devuelve tal cual en lugar
 * de ocultarse: si la búsqueda gana un camino nuevo, la UI lo dice aunque no
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

/** La fuente que combina significado y texto: la única en la que «Tipo de coincidencia» interviene. */
export const FUENTE_CON_SIGNIFICADO = "rrf";
