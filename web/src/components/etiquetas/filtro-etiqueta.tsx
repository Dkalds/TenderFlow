"use client";

/**
 * F1.6 — filtro por etiqueta de organización, el mismo en Oportunidades, el
 * Radar y Detalle.
 *
 * **Dónde filtra.** Detalle y el tablero de oportunidades lo mandan al
 * servidor (`GET /licitaciones?etiqueta=` y `GET /pursuits?etiqueta=`, CU-28):
 * filtran el conjunto entero y su total es el del conjunto etiquetado. El
 * ranking del Radar no acepta etiqueta, así que allí `useFiltroEtiqueta` filtra
 * en cliente el top que la pantalla ya tiene; por eso el selector dice su
 * alcance donde la lista es parcial, y no se cuenta ningún total a partir de
 * él (ADR-014).
 *
 * Sin etiquetas en la organización el selector no aparece: un filtro que no
 * puede filtrar nada es un control inerte.
 */

import * as React from "react";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type EtiquetaAplicada,
  type ObjetoEtiquetable,
  useEtiquetas,
  useEtiquetasDe,
} from "@/hooks/use-etiquetas";
import { cn } from "@/lib/utils";

/** Valor del selector que no filtra. */
export const TODAS_LAS_ETIQUETAS = "todas";

/** ¿El objeto pasa el filtro? `TODAS_LAS_ETIQUETAS` no filtra. */
export function pasaFiltroEtiqueta(
  etiquetas: readonly EtiquetaAplicada[] | undefined,
  filtro: string,
): boolean {
  return filtro === TODAS_LAS_ETIQUETAS || (etiquetas ?? []).some((e) => String(e.id) === filtro);
}

export interface FiltroEtiqueta {
  filtro: string;
  setFiltro: (filtro: string) => void;
  activo: boolean;
  /** Las etiquetas de cada objeto aún no han llegado: no se puede decidir. */
  cargando: boolean;
  /** ¿Pasa el objeto `id`? Mientras carga, nada pasa: filtrar es excluir. */
  pasa: (id: string) => boolean;
}

/**
 * Estado del filtro y la consulta de etiquetas de los `ids` visibles.
 *
 * Las etiquetas por objeto sólo se piden con el filtro puesto: sin él no hay
 * nada que decidir y la petición sería ruido en cada carga del Radar.
 */
export function useFiltroEtiqueta(
  objetoTipo: ObjetoEtiquetable,
  ids: readonly string[],
): FiltroEtiqueta {
  const [filtro, setFiltro] = React.useState<string>(TODAS_LAS_ETIQUETAS);
  const activo = filtro !== TODAS_LAS_ETIQUETAS;
  const porObjeto = useEtiquetasDe(objetoTipo, activo ? ids : []);
  const mapa = porObjeto.data;
  const pasa = React.useCallback(
    (id: string) => !activo || (mapa != null && pasaFiltroEtiqueta(mapa[id], filtro)),
    [activo, mapa, filtro],
  );
  // `isPending` y no `isLoading`: con la organización todavía sin resolver la
  // consulta está retenida y `isLoading` diría que ya no carga, así que el
  // filtro escondería las filas cuyas etiquetas aún no han llegado. La
  // condición de `ids` replica la del hook, que sin ids no pide nada y se
  // quedaría en «cargando» para siempre sobre una lista vacía.
  const cargando = activo && ids.length > 0 && porObjeto.isPending;
  return { filtro, setFiltro, activo, cargando, pasa };
}

// `React.lazy` y no `next/dynamic`: el hueco tiene que medir lo mismo que el
// disparador, y su tamaño llega por `className` (el Radar lo cambia), que el
// `loading` de `next/dynamic` no recibe. En servidor nunca se llega a pintar:
// sin etiquetas cargadas el filtro devuelve `null`.
const SelectorEtiqueta = React.lazy(() =>
  import("./selector-etiqueta").then((modulo) => ({ default: modulo.SelectorEtiqueta })),
);

export function FiltroEtiquetaSelect({
  value,
  onChange,
  alcance,
  className,
}: {
  value: string;
  onChange: (filtro: string) => void;
  /** Qué filas filtra, si no son todas: «en esta página», «en el top del Radar». */
  alcance?: string;
  className?: string;
}) {
  const etiquetas = useEtiquetas().data ?? [];
  if (etiquetas.length === 0) return null;
  return (
    <React.Suspense fallback={<Skeleton className={cn("h-7 w-44", className)} />}>
      <SelectorEtiqueta etiquetas={etiquetas} value={value} onChange={onChange} alcance={alcance} className={className} />
    </React.Suspense>
  );
}
