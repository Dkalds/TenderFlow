"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

/**
 * v148 — criterios, garantías y solvencia tal como los publica PLACSP.
 *
 * `GET /licitaciones/{id}/condiciones-oficiales` es la fuente primaria de esas
 * familias; la ficha del pliego (`use-tender-fact-sheet`) es la extracción LLM
 * que la complementa. Se piden por separado a propósito: son dos procedencias
 * y la pantalla las enseña por separado.
 */
export type CondicionesOficiales = Schemas["CondicionesOficiales"];
export type CondicionesAmbito = Schemas["CondicionesAmbito"];
export type CriterioOficial = Schemas["CriterioOficial"];
export type GarantiaOficial = Schemas["GarantiaOficial"];
export type RequisitoSolvenciaOficial = Schemas["RequisitoSolvenciaOficial"];

const clave = (licitacionId: string) => ["condiciones-oficiales", licitacionId] as const;

export function useCondicionesOficiales(licitacionId: string | null) {
  return useQuery({
    queryKey: clave(licitacionId ?? ""),
    queryFn: () =>
      fetchWithAuth<CondicionesOficiales>(
        `/api/v1/licitaciones/${encodeURIComponent(licitacionId!)}/condiciones-oficiales`,
      ),
    enabled: Boolean(licitacionId),
    // Solo cambia cuando la ingesta vuelve a leer el anuncio: unas horas.
    staleTime: 10 * 60 * 1000,
    meta: META_ERROR_EN_LINEA,
  });
}
