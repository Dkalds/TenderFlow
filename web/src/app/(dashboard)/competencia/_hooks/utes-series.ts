/**
 * Las derivaciones de la vista de UTEs, como funciones puras.
 *
 * No hay fetch ni React: reciben lo que `use-utes-data.ts` ya descargó. La
 * agregación real (quién forma UTE con quién, cuánto suma cada par) la hace el
 * backend; esto sólo da forma a lo recibido —ordenar, filtrar por el buscador y
 * repartir en tramos— sin inventar ninguna cifra nueva.
 */

import { formatCurrency, formatNumber } from "@/lib/utils";

import type {
  ComparativaRow,
  DistribucionBin,
  TablaComparativa,
  TopMiembro,
} from "./utes-types";

/** Las tres filas de la comparativa UTE vs individual, ya formateadas. */
export function buildComparativaRows(
  comparativa: TablaComparativa | undefined,
): ComparativaRow[] {
  if (!comparativa) return [];
  return [
    {
      metrica: "Contratos",
      ute: formatNumber(comparativa.ute.contratos),
      individual: formatNumber(comparativa.individual.contratos),
    },
    {
      metrica: "Importe medio",
      ute: formatCurrency(comparativa.ute.importe_medio),
      individual: formatCurrency(comparativa.individual.importe_medio),
    },
    {
      metrica: "Importe total",
      ute: formatCurrency(comparativa.ute.importe_total),
      individual: formatCurrency(comparativa.individual.importe_total),
    },
  ];
}

/** Buscador de la tabla de miembros: por nombre, sin distinguir mayúsculas. */
export function filterMiembros(
  miembros: TopMiembro[] | undefined,
  search: string,
): TopMiembro[] {
  if (!miembros) return [];
  if (!search) return miembros;
  const q = search.toLowerCase();
  return miembros.filter((m) => m.nombre.toLowerCase().includes(q));
}

const BIN_ORDER = ["1", "2-3", "4-5", "6-10", "11+"];

function bin(count: number): string {
  if (count <= 1) return "1";
  if (count <= 3) return "2-3";
  if (count <= 5) return "4-5";
  if (count <= 10) return "6-10";
  return "11+";
}

/**
 * Histograma de participaciones: cuántos miembros caen en cada tramo.
 *
 * Los tramos vacíos no se pintan —una barra a cero se lee como «medido y
 * ninguno», y aquí no hay tal medición para el tramo que el dataset no alcanza.
 */
export function buildMemberDistribution(
  miembros: TopMiembro[] | undefined,
): DistribucionBin[] {
  if (!miembros?.length) return [];
  const bins: Record<string, number> = {};
  for (const m of miembros) {
    const tramo = bin(m.count);
    bins[tramo] = (bins[tramo] ?? 0) + 1;
  }
  return BIN_ORDER.filter((k) => bins[k]).map((k) => ({
    rango: `${k} UTEs`,
    miembros: bins[k],
  }));
}

/** Top 15 por importe, descartando a quien no reporta importe conjunto. */
export function buildTopMiembrosPorImporte(
  miembros: TopMiembro[] | undefined,
): TopMiembro[] {
  if (!miembros?.length) return [];
  return [...miembros]
    .filter((m) => m.importe > 0)
    .sort((a, b) => b.importe - a.importe)
    .slice(0, 15);
}
