/**
 * Formas que se mueven entre la página del Investigador y sus piezas.
 *
 * `SearchResult` es el hit de `POST /api/v1/search/semantic` tal cual llega:
 * la API devuelve `descripcion` (SemanticHit) y esta vista esperaba
 * `description`, de ahí que ambos nombres convivan hasta que el contrato se
 * unifique.
 */

/** Los dos modos de la consola: búsqueda semántica o conversación con el LLM. */
export type Mode = "search" | "ask";

export interface SearchResult {
  id_externo?: string;
  titulo?: string;
  organo_contratacion?: string;
  organo?: string;
  importe?: number;
  score?: number;
  descripcion?: string;
  description?: string;
  id?: string;
  expediente?: string;
}

/** Ajustes que el usuario persiste en `localStorage`, no en el servidor. */
export interface InvestigadorConfig {
  topK: number;
  /** Peso semántico de la fusión RRF; viaja al backend como `alpha`. */
  alpha: number;
  model: string;
  useGlobalFilters: boolean;
}
