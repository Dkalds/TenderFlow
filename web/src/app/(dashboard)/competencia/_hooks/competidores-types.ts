/**
 * Tipos del contrato de Competidores.
 *
 * Viven aparte de los módulos que los usan porque los comparten tres: la tabla
 * (`competidores-tabla.ts`), las series de gráfico (`competidores-series.ts`) y
 * el hook que las agrega (`use-competidores-view.ts`). Un fichero de tipos sin
 * lógica es lo único que evita que uno de los tres importe a otro sólo para
 * llegar a un `interface`.
 */

export interface Competitor {
  nombre: string;
  empresa_id?: number | null;
  nif?: string | null;
  empresa_ids?: number[];
  nifs?: string[];
  nombres_variantes?: string[];
  es_agrupacion?: boolean;
  count: number;
  importe: number;
  cuota: number;
  contratos_por_anio?: number;
  importe_medio?: number;
  baja_media?: number;
  n_organos?: number;
  ofertas_medias?: number;
  pct_monopolio?: number;
  pct_top_organo?: number;
  ultima?: string;
}

export interface HeatmapEntry {
  ccaa: string;
  empresa: string;
  count: number;
}

export interface BajaItem {
  grupo: string;
  grupo_id?: number;
  contratos: number;
  baja_media_pct: number | null;
}

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
 * bajo las que aparece en la fuente. Los puntos de la dispersión lo cumplen sin
 * ser competidores completos, y por eso el filtro es genérico.
 */
export interface Searchable {
  nombre: string;
  nif?: string | null;
  nifs?: string[];
  nombres_variantes?: string[];
}
