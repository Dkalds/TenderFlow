"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";

/**
 * Fuente de la bandeja «Próximas» (T5): `GET /api/v1/radar/proximas`.
 *
 * Es la otra mitad del Radar. La bandeja normal ordena lo que ya se puede
 * ofertar; ésta lista lo que el órgano **ha anunciado que va a comprar** y
 * todavía no ha sacado a licitación: los estados `PRE` (anuncio previo del art.
 * 134 LCSP) y `CPM` (consulta preliminar de mercado), abiertos.
 *
 * Aquí no se calcula nada (ADR-014). El filtro por estado, el juicio de
 * «abierta», el orden por fecha prevista y los dos denominadores (`total`,
 * `con_fecha_prevista`) los resuelve el backend sobre el corpus entero; este
 * hook sólo transporta. En particular **la fecha prevista no se deriva**: llega
 * si la fuente la publicó y llega `null` si no, y `null` se pinta «sin fecha».
 *
 * Se pide siempre, no sólo con la bandeja abierta: el contador del segmento es
 * lo que le dice al usuario si merece la pena mirarla, y un contador que sólo
 * aparece al pulsar no informa de nada.
 */

/**
 * Formas del endpoint, derivadas del esquema generado y no re-tecleadas: una
 * interfaz escrita a mano deja de coincidir con `api/routes/radar.py` en
 * silencio, y aquí lo que se transporta es precisamente el denominador que la
 * pantalla enseña.
 */
export type RadarProxima = Schemas["RadarProxima"];
export type RadarProximasResult = Schemas["RadarProximasResult"];

/**
 * Cuántas filas se piden. Cabe la bandeja entera con holgura: la medición del
 * spike (`docs/plans/2026-09-spike-planes-anuales-placsp.md`) dice que `PRE` es
 * el 0,14 % del flujo de PLACSP y que `CPM` no entra por ahí. Si algún día el
 * `total` supera este tope, la cabecera lo dirá comparando `total` con las
 * filas recibidas en vez de callarlo.
 */
const LIMITE_PROXIMAS = 100;

export interface RadarProximasConsola {
  items: RadarProxima[];
  /** `null` mientras no se sabe: un «0» durante la carga afirma que no hay. */
  total: number | null;
  conFechaPrevista: number | null;
  /**
   * Los códigos que el servidor aplicó, tal cual. La pantalla los enseña en vez
   * de dar por hecho cuáles son: si el universo de la bandeja cambia en backend,
   * lo que se lee arriba cambia con él en lugar de seguir prometiendo lo de ayer.
   */
  estados: string[];
  /** Filas que existen y no caben en la página pedida. */
  truncadas: number;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}

export function useRadarProximas(): RadarProximasConsola {
  const query = useQuery<RadarProximasResult>({
    queryKey: ["radar", "proximas", LIMITE_PROXIMAS],
    queryFn: () => fetchWithAuth(`/api/v1/radar/proximas?limit=${LIMITE_PROXIMAS}`),
    staleTime: 5 * 60_000,
  });

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? null;

  return {
    items,
    total,
    conFechaPrevista: query.data?.con_fecha_prevista ?? null,
    estados: query.data?.estados ?? [],
    truncadas: total == null ? 0 : Math.max(0, total - items.length),
    isLoading: query.isPending,
    error: query.error,
    refetch: () => {
      void query.refetch();
    },
  };
}
