"use client";

import { useState, useMemo } from "react";
import dynamic from "next/dynamic";
const SankeyChart = dynamic(
  () => import("@/components/charts/sankey-chart").then((m) => ({ default: m.SankeyChart })),
  { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-md" /> },
);
import { ExportPopover } from "@/components/export-popover";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { t } from "@/lib/i18n";
import { getEstadoChartColor } from "@/lib/chart-colors";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { TimelineSection } from "./_components/timeline-section";
import { MarketIndicators } from "./_components/market-indicators";
import { PeriodComparison } from "./_components/period-comparison";
import { FunnelEstados } from "./_components/funnel-estados";
import { NovedadesBanner } from "./_components/novedades-banner";
import { KpiRows } from "./_components/kpi-rows";
import { TopLicitacionesList } from "./_components/top-licitaciones-list";
import { EstadoTiposCharts } from "./_components/estado-tipos-charts";
import { ActivityTechCharts } from "./_components/activity-tech-charts";
import { EvolucionMensual } from "./_components/evolucion-mensual";
import { TopOrganosChart } from "./_components/top-organos-chart";
import type { TimelineItem, ExtendedOverview, CompareResponse } from "./_components/types";
import type {
  ResumenNovedadesResult,
  ResumenHoyResult,
  TimelineScatterResult,
  SankeyResult,
  TopLicitacionesResult,
  TecnologiasResult,
  ProyectosModulosResult,
} from "@/generated/api";

export default function ResumenPage() {
  const { comparar, setComparar, rango, rangoB } = useFilters();
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

  const sankey = useFilteredQuery<SankeyResult>(
    ["analytics", "resumen", "sankey"],
    "/api/v1/analytics/resumen/sankey",
    { staleTime: 5 * 60 * 1000 },
  );

  // eslint-disable-next-line react-hooks/purity
  const timelineDesde = rango.desde ?? new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  const timeline = useFilteredQuery<TimelineScatterResult>(
    ["analytics", "resumen", "timeline", timelineDesde],
    "/api/v1/analytics/resumen/timeline",
    { staleTime: 5 * 60 * 1000 },
    { fecha_desde: timelineDesde },
  );

  const top = useFilteredQuery<TopLicitacionesResult>(
    ["analytics", "resumen", "top"],
    "/api/v1/analytics/resumen/top",
    { staleTime: 5 * 60 * 1000 },
  );

  const compare = useFilteredQuery<CompareResponse>(
    ["analytics", "compare-periods", rango.desde ?? "", rango.hasta ?? "", rangoB.desde ?? "", rangoB.hasta ?? ""],
    "/api/v1/analytics/compare-periods",
    {
      staleTime: 5 * 60 * 1000,
      enabled: comparar && !!rango.desde && !!rangoB.desde,
    },
  );

  const tecnologias = useFilteredQuery<TecnologiasResult>(
    ["analytics", "tecnologias"],
    "/api/v1/analytics/tecnologias",
    { staleTime: 5 * 60 * 1000 },
  );

  const tiposProyecto = useFilteredQuery<ProyectosModulosResult>(
    ["analytics", "proyectos-modulos"],
    "/api/v1/analytics/proyectos-modulos",
    { staleTime: 5 * 60 * 1000 },
  );

  const data = overview.data;
  const isLoading = overview.isLoading;

  const scatterData =
    timeline.data?.items?.map((item) => ({
      x: new Date(item.fecha_publicacion ?? "").getTime(),
      y: item.importe ?? 0,
      z: item.importe ?? 0,
      titulo: item.titulo ?? "",
      estado: item.estado ?? "",
      fill: getEstadoChartColor(item.estado),
    })) ?? [];

  const tiposData = useMemo(() => {
    const raw = tiposProyecto.data?.tipos_proyecto;
    if (!raw) return [];
    return [...raw].sort((a, b) => a.count - b.count);
  }, [tiposProyecto.data]);

  const techData = useMemo(() => {
    const raw = tecnologias.data?.tecnologias;
    if (!raw) return [];
    return [...raw].sort((a, b) => b.count - a.count).slice(0, 10);
  }, [tecnologias.data]);

  const sortedPubs = useMemo(() => {
    const items = [...(timeline.data?.items ?? [])] as TimelineItem[];
    items.sort((a, b) => {
      const av = a[pubSortKey];
      const bv = b[pubSortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return pubSortDir === "asc" ? av - bv : bv - av;
      const cmp = String(av).localeCompare(String(bv), "es", { sensitivity: "base" });
      return pubSortDir === "asc" ? cmp : -cmp;
    });
    return items;
  }, [timeline.data?.items, pubSortKey, pubSortDir]);

  const togglePubSort = (key: keyof TimelineItem) => {
    if (pubSortKey === key) {
      setPubSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setPubSortKey(key);
      setPubSortDir("asc");
    }
    setPubPage(0);
  };

  if (overview.error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">
          {t("common.error")}: {(overview.error as Error).message}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Resumen</h1>
          <p className="text-muted-foreground">
            Top licitaciones, distribucion por estado y salud competitiva del mercado.
          </p>
        </div>
        <ExportPopover />
      </div>

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

      <TopLicitacionesList data={top.data} isLoading={top.isLoading} />

      <EstadoTiposCharts
        porEstado={data?.por_estado}
        tiposProyectoData={tiposData}
        isLoading={isLoading}
        tiposLoading={tiposProyecto.isLoading}
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Flujo Tipo → Estado</CardTitle>
        </CardHeader>
        <CardContent>
          {sankey.isLoading ? (
            <Skeleton className="h-[420px] w-full" />
          ) : sankey.data?.nodes && sankey.data.nodes.length > 0 ? (
            <SankeyChart
              nodes={sankey.data.nodes}
              links={sankey.data.links}
              className="h-[420px]"
            />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      <MarketIndicators data={data} isLoading={isLoading} />

      <PeriodComparison
        comparar={comparar}
        setComparar={setComparar}
        rango={rango}
        rangoB={rangoB}
        compare={compare}
      />

      <ActivityTechCharts
        activityData={data?.por_mes?.slice(-12) ?? []}
        techData={techData}
        isLoading={isLoading}
        techLoading={tecnologias.isLoading}
      />

      <EvolucionMensual porMes={data?.por_mes} isLoading={isLoading} />

      <TopOrganosChart topOrganos={data?.top_organos} isLoading={isLoading} />

      <FunnelEstados funnelEstados={data?.funnel_estados ?? []} />
    </div>
  );
}
