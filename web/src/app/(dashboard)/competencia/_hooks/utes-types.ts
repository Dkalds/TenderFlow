/**
 * Tipos del contrato de UTEs (`/api/v1/analytics/utes`).
 *
 * Viven aparte por lo mismo que los de Competidores: los comparten el hook que
 * descarga (`use-utes-data.ts`), las derivaciones puras (`utes-series.ts`) y los
 * cuatro componentes que pintan. Un fichero de tipos sin lógica evita que uno
 * importe a otro sólo para llegar a un `interface`.
 */

export interface UTEsKpis {
  total_ute: number;
  importe_ute: number;
  ticket_medio_ute: number;
  ticket_medio_individual: number;
  empresas_distintas: number;
}

export interface TopMiembro {
  nombre: string;
  count: number;
  importe: number;
}

export interface EvolucionEntry {
  periodo: string;
  count: number;
  importe: number;
}

export interface TablaComparativa {
  ute: { contratos: number; importe_medio: number; importe_total: number };
  individual: { contratos: number; importe_medio: number; importe_total: number };
}

export interface SocioPar {
  empresa_a: string;
  empresa_b: string;
  contratos: number;
  importe: number;
}

export interface UTEsData {
  kpis: UTEsKpis;
  top_miembros: TopMiembro[];
  socios_frecuentes?: SocioPar[];
  evolucion: EvolucionEntry[];
  tabla_comparativa: TablaComparativa;
}

/** Fila ya formateada de la comparativa UTE vs individual. */
export interface ComparativaRow {
  metrica: string;
  ute: string;
  individual: string;
}

/** Un tramo del histograma de participaciones por miembro. */
export interface DistribucionBin {
  rango: string;
  miembros: number;
}
