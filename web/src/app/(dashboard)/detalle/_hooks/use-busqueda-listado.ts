"use client";

/**
 * F1.1 — `busqueda_realizada` desde el listado, con cuántos filtros llevaba.
 *
 * El catálogo ya declaraba `superficie: "listado"` y `filtros`, pero nadie lo
 * emitía: sólo medían la paleta y el Investigador. Sin esta pieza la pregunta
 * de F1.1 —¿se usan los filtros nuevos, o la gente sigue buscando por texto?—
 * no tenía respuesta.
 *
 * Una vez por combinación de filtros con respuesta, no por página ni por
 * orden: paginar es seguir leyendo la misma búsqueda. Sin ningún filtro no hay
 * búsqueda que medir (es abrir la tabla). Nunca viaja qué filtros: sólo cuántos,
 * en tramos (`tramoDeFiltros`).
 */

import { useEffect, useRef } from "react";
import { registrarEvento, tramoDeFiltros } from "@/lib/analytics";

/**
 * Filtros activos contados como los ve el usuario: el periodo es uno aunque
 * viaje en dos parámetros.
 */
export function contarFiltros(params: Record<string, string>): number {
  const claves = new Set(Object.keys(params).filter((clave) => params[clave] !== ""));
  if (claves.has("fecha_desde") && claves.has("fecha_hasta")) claves.delete("fecha_hasta");
  return claves.size;
}

export function useBusquedaListado(
  filtros: Record<string, string>,
  resultado: { total: number } | undefined,
  cargando: boolean,
): void {
  const ultima = useRef<string | null>(null);
  useEffect(() => {
    if (cargando || !resultado) return;
    const n = contarFiltros(filtros);
    if (n === 0) return;
    const clave = JSON.stringify(Object.entries(filtros).sort());
    if (ultima.current === clave) return;
    ultima.current = clave;
    registrarEvento("busqueda_realizada", {
      superficie: "listado",
      con_resultados: resultado.total > 0 ? "si" : "no",
      filtros: tramoDeFiltros(n),
    });
  }, [filtros, resultado, cargando]);
}
