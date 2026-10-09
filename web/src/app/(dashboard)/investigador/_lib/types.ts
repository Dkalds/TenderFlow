/**
 * Formas que se mueven entre la página del Investigador y sus piezas.
 *
 * El resultado y lo entendido de la frase salen del contrato generado
 * (`POST /api/v1/search/semantic`): la vista no declara su propia copia. Hasta
 * 2026-10 lo hacía —con `description` junto a `descripcion`, `organo` junto a
 * `organo_contratacion`, todo opcional— y por eso la tarjeta no enseñaba el
 * estado, la comunidad ni la fecha que la API llevaba meses devolviendo.
 */

import type { Interpretacion, SemanticHit, SemanticSearchResponse, TramoTexto } from "@/lib/api-types";

export type SearchResult = SemanticHit;
export type { Interpretacion, SemanticSearchResponse, TramoTexto };

/** Ajustes que el usuario persiste en `localStorage`, no en el servidor. */
export interface InvestigadorConfig {
  topK: number;
  /**
   * «Tipo de coincidencia»: cuánto pesa el significado frente a las palabras
   * exactas cuando la búsqueda combina las dos cosas; viaja como `alpha`. El
   * control solo aparece si una respuesta ha llegado por ese camino.
   */
  alpha: number;
  model: string;
  useGlobalFilters: boolean;
}
