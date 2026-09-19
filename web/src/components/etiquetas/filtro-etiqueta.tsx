"use client";

/**
 * F1.6 — filtro por etiqueta de organización, el mismo en Oportunidades, el
 * Radar y Detalle.
 *
 * **Filtra lo cargado, no el corpus.** Ningún listado del backend acepta un
 * parámetro de etiqueta (ni `GET /licitaciones` ni el ranking del Radar), así
 * que el filtro se aplica en cliente sobre las filas que la pantalla ya tiene:
 * el top-24 del Radar, la página visible de Detalle, las oportunidades del
 * tablero. Por eso el selector lo dice («en esta página») donde la lista es
 * una página y no el conjunto entero, y por eso no se cuenta ningún total a
 * partir de él (ADR-014).
 *
 * Sin etiquetas en la organización el selector no se pinta: un filtro que no
 * puede filtrar nada es un control inerte.
 */

import * as React from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
  return { filtro, setFiltro, activo, cargando: activo && porObjeto.isLoading, pasa };
}

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
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        className={cn("h-7 w-44 text-xs", className)}
        aria-label={alcance ? `Filtrar por etiqueta ${alcance}` : "Filtrar por etiqueta"}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={TODAS_LAS_ETIQUETAS}>Todas las etiquetas</SelectItem>
        {etiquetas.map((etiqueta) => (
          <SelectItem key={etiqueta.id} value={String(etiqueta.id)}>
            {etiqueta.nombre}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
