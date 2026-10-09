/**
 * Tipos del contrato de Competidores.
 *
 * Salen del OpenAPI generado, no de una declaración a mano. Hasta 2026-10 esta
 * pantalla escribía sus propios `interface`, y el compilador no vio que leía
 * dos campos (`cobertura_ofertas_pct`, `top_competidor`) que la respuesta nunca
 * trajo: con tipos a mano, un nombre que el backend no envía compila igual.
 *
 * Viven aparte de los módulos que los usan porque los comparten cuatro: la
 * tabla (`competidores-tabla.ts`), las series (`competidores-series.ts`), los
 * vigilados (`vigilados.ts`) y el hook que los agrega.
 */

import type { Schemas } from "@/lib/api-types";

export type Competitor = Schemas["CompetitorEntry"];

export type HeatmapEntry = Schemas["HeatmapCcaaCell"];

export type EstacionalidadEntry = Schemas["EstacionalidadEntry"];

/**
 * La respuesta de `/analytics/competitors`.
 *
 * `cobertura_ofertas_pct` es el denominador de `pct_oferta_unica`: qué parte de
 * las licitaciones trae el número de ofertantes. Puede no venir (`null` = sin
 * medir, o un backend desplegado anterior al campo); sin él, la celda «Oferta
 * única» se abstiene (`lib/cobertura`), que es la salida segura.
 */
export type CompetitorsData = Schemas["CompetitorResult"];

/** Medida que ordena el ranking y gobierna el titular y el reparto. */
export type Metrica = "importe" | "count";

/** Lente del mapa de competidores: qué dos medidas forman el plano. */
export type Lente = "precio" | "clientes";

export type SortKey =
  | "nombre"
  | "count"
  | "importe"
  | "cuota"
  | "contratos_por_anio"
  | "importe_medio"
  | "baja_media"
  | "nif"
  | "ofertas_medias"
  | "pct_monopolio"
  | "pct_top_organo"
  | "ultima";

/**
 * Lo mínimo que necesita una fila para ser buscable: su nombre y las identidades
 * bajo las que aparece en la fuente.
 */
export interface Searchable {
  nombre: string;
  nif?: string | null;
  nifs?: string[];
  nombres_variantes?: string[];
}
