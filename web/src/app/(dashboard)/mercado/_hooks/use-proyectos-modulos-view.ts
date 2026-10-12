"use client";

/**
 * Datos y series de la vista «Proyectos y módulos».
 *
 * Desde 2026-10 la vista agrupa por familias de la taxonomía (ERP, CRM, cloud,
 * ciberseguridad…) y los módulos SAP son el desglose de ERP. Todo lo que aquí
 * se calcula es **presentación** (ordenar, recortar a top-N, pivotar filas a
 * columnas para el apilado): los totales y ratios llegan calculados del
 * backend, como exige ADR-014. Las únicas derivadas aritméticas que quedan son
 * `importe_medio` por módulo y el importe medio de S/4HANA, divisiones de dos
 * campos de la misma fila que no cambian de universo; el de las familias ya
 * llega hecho.
 */

import { useMemo } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import type { Schemas } from "@/lib/api-types";

/**
 * Contrato REAL del endpoint, derivado del esquema OpenAPI.
 *
 * Antes era una `interface` escrita a mano que declaraba `total`,
 * `total_modulos` y `total_tipos`: tres campos que el backend nunca emitió.
 * TypeScript los daba por buenos, llegaban como `undefined` y activaban
 * fallbacks — el de `total` dividía por la suma de filas de módulo (una
 * licitación con módulos A+B cuenta dos veces), así que el KPI leía MÁS BAJO
 * cuanto más multi-módulo era el corpus. Derivar el tipo del esquema hace que
 * `npm run typecheck` delate esa divergencia en vez de la pantalla.
 */
export type ProyectosModulosResponse = Schemas["ProyectosModulosResult"];

/** Sentinel used by the backend to flag a brand-new module (no prior-year data). */
export const YOY_NUEVO = 999;

/**
 * Una fila de las tablas ordenables: una familia o un módulo SAP, con lo que
 * se compara entre ellas.
 */
export interface FilaCategoria {
  nombre: string;
  count: number;
  importe: number;
  importe_medio: number;
}

export type TipoProyectoRow = Schemas["ProyectoTipoEntry"];

export type TipoEstadoRow = { tipo: string; [estado: string]: number | string };

/** Nodo de treemap: nombre y tamaño (el importe). */
export interface NodoImporte {
  name: string;
  size: number;
  [key: string]: string | number;
}

/** Los `limite` nodos de más importe, sin los que no tienen. */
function nodosDeImporte(filas: FilaCategoria[], limite: number): NodoImporte[] {
  return filas
    .filter((fila) => fila.importe > 0)
    .sort((a, b) => b.importe - a.importe)
    .slice(0, limite)
    .map((fila) => ({ name: fila.nombre, size: fila.importe }));
}

export function useProyectosModulosView() {
  const { data, isLoading, error, refetch } = useFilteredQuery<ProyectosModulosResponse>(
    ["analytics", "proyectos-modulos"],
    "/api/v1/analytics/proyectos-modulos",
    // El error lo pinta la vista en línea (PanelError): sin toast además.
    { staleTime: 5 * 60 * 1000, meta: META_ERROR_EN_LINEA },
  );

  // Las familias llegan ordenadas de más a menos licitaciones y con su importe
  // medio: aquí solo se les da la forma de fila.
  const familias = useMemo<FilaCategoria[]>(
    () =>
      (data?.familias ?? []).map((f) => ({
        nombre: f.etiqueta,
        count: f.count,
        importe: f.importe,
        importe_medio: f.importe_medio,
      })),
    [data],
  );

  const modulos = useMemo<FilaCategoria[]>(
    () =>
      [...(data?.modulos ?? [])]
        .sort((a, b) => b.count - a.count)
        .map((m) => ({
          nombre: m.modulo,
          count: m.count,
          importe: m.importe,
          importe_medio: m.count > 0 ? m.importe / m.count : 0,
        })),
    [data],
  );

  const tipos = useMemo(() => data?.tipos_proyecto ?? [], [data]);

  const ticketS4Hana = useMemo(() => {
    const s4 = modulos.find((m) => /s\/?4hana/i.test(m.nombre));
    return s4 && s4.count > 0 ? s4.importe_medio : null;
  }, [modulos]);

  const tiposPie = useMemo(() => {
    const sorted = [...tipos].sort((a, b) => b.count - a.count);
    if (sorted.length <= 8) return sorted;
    const top = sorted.slice(0, 7);
    const rest = sorted.slice(7);
    return [
      ...top,
      {
        tipo: "Otros",
        count: rest.reduce((s, i) => s + i.count, 0),
        importe: rest.reduce((s, i) => s + i.importe, 0),
      },
    ];
  }, [tipos]);

  const familiasTreemap = useMemo(() => nodosDeImporte(familias, 20), [familias]);
  const modulosTreemap = useMemo(() => nodosDeImporte(modulos, 25), [modulos]);
  const tiposTreemap = useMemo(
    () =>
      nodosDeImporte(
        tipos.map((t) => ({ nombre: t.tipo, count: t.count, importe: t.importe, importe_medio: 0 })),
        20,
      ),
    [tipos],
  );

  // Tipo de proyecto x Estado (stacked-bar equivalent of the Streamlit sunburst)
  const tipoEstadoEstados = useMemo(() => {
    const set = new Set<string>();
    for (const r of data?.tipo_estado ?? []) set.add(r.estado);
    return [...set];
  }, [data]);

  const tipoEstadoData = useMemo(() => {
    const byTipo = new Map<string, Record<string, number | string>>();
    const totals = new Map<string, number>();
    for (const r of data?.tipo_estado ?? []) {
      totals.set(r.tipo, (totals.get(r.tipo) ?? 0) + r.n);
      if (!byTipo.has(r.tipo)) byTipo.set(r.tipo, { tipo: r.tipo });
      byTipo.get(r.tipo)![r.estado] = r.n;
    }
    return [...byTipo.values()]
      .sort((a, b) => (totals.get(String(b.tipo)) ?? 0) - (totals.get(String(a.tipo)) ?? 0))
      .slice(0, 12) as TipoEstadoRow[];
  }, [data]);

  return {
    data,
    familias,
    modulos,
    tipos,
    ticketS4Hana,
    tiposPie,
    familiasTreemap,
    modulosTreemap,
    tiposTreemap,
    tipoEstadoEstados,
    tipoEstadoData,
    isLoading,
    error,
    /** El «Reintentar» del error. */
    refetch: () => void refetch(),
  };
}
