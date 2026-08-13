"use client";

import { useMemo, useState } from "react";
import { ExportPopover } from "@/components/export-popover";
import { CopilotBar } from "@/components/copilot-panel";
import { getEstadoChartColor } from "@/lib/chart-colors";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { TimelineSection } from "./_components/timeline-section";
import { NovedadesBanner } from "./_components/novedades-banner";
import { KpiRows } from "./_components/kpi-rows";
import { EventosFeed } from "./_components/eventos-feed";
import { AtajosAnalisis } from "./_components/atajos-analisis";
import type { TimelineItem, ExtendedOverview } from "./_components/types";
import type {
  ResumenNovedadesResult,
  ResumenHoyResult,
  TimelineScatterResult,
} from "@/lib/api-types";

/**
 * Resumen — la entrada del producto.
 *
 * Ocho KPIs con el mismo peso visual no priorizan nada: la pantalla abría con
 * «Vencen 48h» y «Órganos únicos» compitiendo por la misma atención. Aquí lo
 * urgente sube a tarjetas grandes con su destino visible y el contexto baja a
 * una tira compacta con delta y aviso de anomalía. Las 19 capacidades de la
 * pantalla siguen: copiloto, novedades con su muestra de cinco, los ocho KPIs,
 * el scatter, la tabla de siete columnas ordenables con paginación, los atajos
 * y la exportación.
 */
export default function ResumenPage() {
  const { rango } = useFilters();
  const [pubPage, setPubPage] = useState(0);
  const [pubSortKey, setPubSortKey] = useState<keyof TimelineItem>("fecha_publicacion");
  const [pubSortDir, setPubSortDir] = useState<"asc" | "desc">("desc");

  const overview = useFilteredQuery<ExtendedOverview>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 5 * 60 * 1000 },
  );

  const novedades = useFilteredQuery<ResumenNovedadesResult>(
    ["analytics", "resumen", "novedades"],
    "/api/v1/analytics/resumen/novedades",
    { staleTime: 5 * 60 * 1000 },
  );

  const hoy = useFilteredQuery<ResumenHoyResult>(
    ["analytics", "resumen", "hoy"],
    "/api/v1/analytics/resumen/hoy",
    { staleTime: 2 * 60 * 1000 },
    undefined,
    true,
  );

  // Ventana por defecto de 30 días cuando el ámbito no fija fecha de inicio.
  // eslint-disable-next-line react-hooks/purity
  const timelineDesde = rango.desde ?? new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  const timeline = useFilteredQuery<TimelineScatterResult>(
    ["analytics", "resumen", "timeline", timelineDesde],
    "/api/v1/analytics/resumen/timeline",
    { staleTime: 5 * 60 * 1000 },
    { fecha_desde: timelineDesde },
  );

  const data = overview.data;
  const isLoading = overview.isLoading;

  const scatterData = useMemo(
    () =>
      timeline.data?.items?.map((item) => ({
        x: new Date(item.fecha_publicacion ?? "").getTime(),
        y: item.importe ?? 0,
        z: item.importe ?? 0,
        titulo: item.titulo ?? "",
        estado: item.estado ?? "",
        fill: getEstadoChartColor(item.estado),
      })) ?? [],
    [timeline.data?.items],
  );

  const sortedPubs = useMemo(() => {
    const items = [...(timeline.data?.items ?? [])] as TimelineItem[];
    items.sort((a, b) => {
      const left = a[pubSortKey];
      const right = b[pubSortKey];
      if (left == null && right == null) return 0;
      if (left == null) return 1;
      if (right == null) return -1;
      if (typeof left === "number" && typeof right === "number") {
        return pubSortDir === "asc" ? left - right : right - left;
      }
      const compared = String(left).localeCompare(String(right), "es", { sensitivity: "base" });
      return pubSortDir === "asc" ? compared : -compared;
    });
    return items;
  }, [timeline.data?.items, pubSortKey, pubSortDir]);

  // Ordenar por otra columna vuelve a la primera página: «página 3 de otro
  // criterio» no señala las mismas filas.
  const togglePubSort = (key: keyof TimelineItem) => {
    if (pubSortKey === key) {
      setPubSortDir((direction) => (direction === "asc" ? "desc" : "asc"));
    } else {
      setPubSortKey(key);
      setPubSortDir("asc");
    }
    setPubPage(0);
  };

  return (
    <div className="flex h-[calc(100vh-52px)] min-h-0 flex-col">
      <header className="flex h-11 flex-none items-center gap-2.5 border-b border-border/60 px-4">
        <h1 className="font-display text-[13px] font-semibold">Resumen</h1>
        <span className="hidden truncate text-[11.5px] text-muted-foreground lg:inline">
          qué requiere tu atención hoy en el mercado
        </span>
        <div className="flex-1" />
        <ExportPopover className="[&>button]:h-7 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs" />
      </header>

      {overview.error ? (
        <div className="grid flex-1 place-items-center p-10">
          <div
            role="alert"
            className="max-w-[520px] rounded-xl border border-destructive/40 bg-destructive/8 px-6 py-5"
          >
            <div className="mb-2 flex items-center gap-2.5">
              <span className="grid h-5.5 w-5.5 flex-none place-items-center rounded-full border border-destructive/50 text-[12px] font-semibold text-destructive">
                !
              </span>
              <span className="text-[13.5px] font-semibold text-destructive">
                No se pudo cargar el resumen
              </span>
            </div>
            <p className="mb-3.5 font-mono text-xs leading-[1.55] text-destructive/80">
              {(overview.error as Error).message}
            </p>
            <button
              type="button"
              onClick={() => void overview.refetch()}
              className="tf-pressable h-[30px] rounded-md border border-border/80 px-3 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              ↻ Reintentar
            </button>
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-6 pt-4">
          <CopilotBar className="mb-3.5 max-w-[720px]" />

          <NovedadesBanner data={novedades.data} isLoading={novedades.isLoading} />

          <KpiRows
            overview={data}
            hoy={hoy.data}
            isLoading={isLoading}
            hoyLoading={hoy.isLoading}
            porMes={data?.por_mes}
          />

          <TimelineSection
            scatterData={scatterData}
            sortedPubs={sortedPubs}
            isLoading={timeline.isLoading}
            pubPage={pubPage}
            setPubPage={setPubPage}
            pubSortKey={pubSortKey}
            pubSortDir={pubSortDir}
            togglePubSort={togglePubSort}
          />

          {/* Movimientos de contrato del mercado (GET /eventos). Vivía en la
              extinta /pipeline-alertas; su pregunta —"¿qué ha cambiado?"— es
              la de este espacio, no la de la agenda personal de Mi Pipeline. */}
          <div className="mt-4">
            <EventosFeed />
          </div>

          <AtajosAnalisis />
        </div>
      )}
    </div>
  );
}
