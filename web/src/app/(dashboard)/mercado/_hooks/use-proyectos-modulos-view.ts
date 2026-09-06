"use client";

/**
 * Datos y series de la vista «Proyectos y módulos».
 *
 * Todo lo que aquí se calcula es **presentación** (ordenar, recortar a top-N,
 * pivotar filas a columnas para el apilado): los totales y ratios llegan
 * calculados del backend, como exige ADR-014. La única derivada aritmética que
 * queda es `importe_medio` por módulo, que es una división de dos campos de la
 * misma fila y no cambia de universo.
 */

import { useMemo, useState } from "react";

import { useFilteredQuery } from "@/hooks/use-filtered-query";
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
 *
 * El bloque intersección son los campos que este cambio AÑADE a
 * `ProyectosModulosResult` en el backend; se declaran aquí solo hasta que se
 * regenere `api.d.ts` (`make openapi`), que es artefacto generado.
 */
export type ProyectosModulosResponse = Schemas["ProyectosModulosResult"] & {
  total?: number;
  menciones_modulo?: number;
  pct_match_portfolio?: number;
  modulos_por_clasificada?: number;
};

/** Sentinel used by the backend to flag a brand-new module (no prior-year data). */
export const YOY_NUEVO = 999;

export type ModSortKey = "modulo" | "count" | "importe" | "importe_medio";

export type ModuloConMedia = Schemas["ModuloEntry"] & { importe_medio: number };

export type TipoProyectoRow = Schemas["ProyectoTipoEntry"];

export type TipoEstadoRow = { tipo: string; [estado: string]: number | string };

export function useProyectosModulosView() {
  const [modSortKey, setModSortKey] = useState<ModSortKey>("count");
  const [modSortDir, setModSortDir] = useState<"asc" | "desc">("desc");

  const { data, isLoading, error } = useFilteredQuery<ProyectosModulosResponse>(
    ["analytics", "proyectos-modulos"],
    "/api/v1/analytics/proyectos-modulos",
    { staleTime: 5 * 60 * 1000 },
  );

  const modulos = useMemo(() => data?.modulos ?? [], [data]);
  const tipos = useMemo(() => data?.tipos_proyecto ?? [], [data]);

  const ticketS4Hana = useMemo(() => {
    const s4 = modulos.find(
      (m) =>
        m.modulo.toLowerCase().includes("s/4hana") ||
        m.modulo.toLowerCase().includes("s4hana"),
    );
    return s4 && s4.count > 0 ? s4.importe / s4.count : null;
  }, [modulos]);

  const modulosSorted = useMemo(
    () => [...modulos].sort((a, b) => b.count - a.count),
    [modulos],
  );

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

  // Treemap data: modulos by importe
  const modulosTreemap = useMemo(
    () =>
      modulos
        .filter((m) => m.importe > 0)
        .sort((a, b) => b.importe - a.importe)
        .slice(0, 25)
        .map((m) => ({ name: m.modulo, size: m.importe })),
    [modulos],
  );

  const tiposTreemap = useMemo(
    () =>
      tipos
        .filter((t) => t.importe > 0)
        .sort((a, b) => b.importe - a.importe)
        .slice(0, 20)
        .map((t) => ({ name: t.tipo, size: t.importe })),
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

  // Average importe per module table
  const modulosWithAvg = useMemo<ModuloConMedia[]>(
    () =>
      modulos.map((m) => ({
        ...m,
        importe_medio: m.count > 0 ? m.importe / m.count : 0,
      })),
    [modulos],
  );

  const sortedModulosAvg = useMemo(() => {
    const sorted = [...modulosWithAvg];
    sorted.sort((a, b) => {
      const aVal = a[modSortKey];
      const bVal = b[modSortKey];
      if (typeof aVal === "string" && typeof bVal === "string") {
        return modSortDir === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }
      return modSortDir === "asc"
        ? (aVal as number) - (bVal as number)
        : (bVal as number) - (aVal as number);
    });
    return sorted;
  }, [modulosWithAvg, modSortKey, modSortDir]);

  function toggleModSort(key: ModSortKey) {
    if (modSortKey === key) {
      setModSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setModSortKey(key);
      setModSortDir("desc");
    }
  }

  return {
    data,
    modulos,
    tipos,
    ticketS4Hana,
    modulosSorted,
    tiposPie,
    modulosTreemap,
    tiposTreemap,
    tipoEstadoEstados,
    tipoEstadoData,
    sortedModulosAvg,
    toggleModSort,
    isLoading,
    error,
  };
}
