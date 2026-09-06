"use client";

/**
 * Las dos llamadas del panel de publicaciones y lo que se deriva de ellas.
 *
 * **Ritmo e importes salen de una sola llamada** a
 * `GET /analytics/trends?group_by=day`, agregada en backend sobre el periodo
 * completo (ADR-014, y sin el tope de 1.000 filas del timeline). `group_by=day`
 * porque la ventana del Resumen son ~30 días; el techo de puntos lo declara la
 * propia respuesta en `serie_truncada`.
 *
 * **La dispersión pide el timeline con `muestra=true`**, que reparte las 1.000
 * filas por toda la ventana en vez de devolver las 1.000 más recientes. Sin
 * eso, la nube cubría 48 horas de un periodo de 30 días. La tabla de «últimas
 * publicaciones» pide el mismo endpoint SIN el flag —necesita justo las más
 * recientes—, y como `muestra` entra en la clave de React Query las dos
 * conviven en caché sin pisarse. Sólo se pide con el corte a la vista.
 */

import { useMemo } from "react";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import type { HistogramBin, TimelineScatterResult, TrendPoint, TrendsResult } from "@/lib/api-types";
import type { TimelineItem } from "../_components/types";
import {
  leyendaEstados,
  puntosScatter,
  ventanaLabel,
  type Corte,
  type PuntoScatter,
} from "../_components/publicaciones/publicaciones-data";

const STALE_MS = 5 * 60 * 1000;
const VENTANA_DIAS = 30;

export interface Publicaciones {
  /** Copia de la ventana medida: «entre el 1 jul y el 31 jul de 2026». */
  ventana: string;
  serie: TrendPoint[];
  serieTruncada: boolean;
  histograma: HistogramBin[];
  totalHistograma: number;
  maxHistograma: number;
  scatterData: PuntoScatter[];
  leyenda: [string, string][];
  /** Expedientes de la muestra que no declaran importe y no caben en un eje log. */
  sinImporte: number;
  muestreado: boolean;
  /** Publicaciones de la ventana según el propio endpoint del timeline. */
  totalVentana: number;
  cargando: boolean;
  error: unknown;
  refetch: () => void;
  /** Acota el ámbito a un solo día (clic en una barra del ritmo). */
  acotarADia: (dia: string) => void;
}

export function usePublicaciones(corte: Corte): Publicaciones {
  const { rango, setRango } = useFilters();

  // Ventana por defecto de 30 días cuando el ámbito no fija fecha de inicio.
  // eslint-disable-next-line react-hooks/purity
  const desde = rango.desde ?? new Date(Date.now() - VENTANA_DIAS * 86400000).toISOString().slice(0, 10);

  const trends = useFilteredQuery<TrendsResult>(
    ["analytics", "trends", "resumen", desde],
    "/api/v1/analytics/trends?group_by=day",
    { staleTime: STALE_MS },
    { fecha_desde: desde },
  );

  const timeline = useFilteredQuery<TimelineScatterResult>(
    ["analytics", "resumen", "timeline", "muestra", desde],
    "/api/v1/analytics/resumen/timeline",
    { staleTime: STALE_MS, enabled: corte === "dispersion" },
    { fecha_desde: desde, muestra: "true" },
  );

  const histograma = trends.data?.histogram_bins ?? [];

  const items = useMemo(
    () => (timeline.data?.items ?? []) as TimelineItem[],
    [timeline.data?.items],
  );
  const scatterData = useMemo(() => puntosScatter(items), [items]);
  const leyenda = useMemo(() => leyendaEstados(scatterData), [scatterData]);

  const esDispersion = corte === "dispersion";

  return {
    // `fecha_hasta` viaja solo en los params del ámbito; aquí sólo se necesita
    // para nombrar la ventana en la copia.
    ventana: ventanaLabel(desde, rango.hasta),
    serie: trends.data?.series ?? [],
    serieTruncada: trends.data?.serie_truncada ?? false,
    histograma,
    totalHistograma: histograma.reduce((suma, bin) => suma + bin.count, 0),
    maxHistograma: histograma.reduce((mayor, bin) => Math.max(mayor, bin.count), 0),
    scatterData,
    leyenda,
    sinImporte: items.length - scatterData.length,
    muestreado: timeline.data?.muestreado ?? false,
    totalVentana: timeline.data?.total ?? 0,
    cargando: esDispersion ? timeline.isLoading : trends.isLoading,
    error: esDispersion ? timeline.error : trends.error,
    refetch: () => void (esDispersion ? timeline.refetch() : trends.refetch()),
    acotarADia: (dia: string) => setRango({ desde: dia, hasta: dia }),
  };
}
