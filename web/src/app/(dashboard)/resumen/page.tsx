"use client";

import { useState, useMemo } from "react";
import { ExportPopover } from "@/components/export-popover";
import { CopilotBar } from "@/components/copilot-panel";
import { t } from "@/lib/i18n";
import { getEstadoChartColor } from "@/lib/chart-colors";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useFilters } from "@/lib/filters";
import { TimelineSection } from "./_components/timeline-section";
import { NovedadesBanner } from "./_components/novedades-banner";
import { KpiRows } from "./_components/kpi-rows";
import { AtajosAnalisis } from "./_components/atajos-analisis";
import type { TimelineItem, ExtendedOverview } from "./_components/types";
import type {
  ResumenNovedadesResult,
  ResumenHoyResult,
  TimelineScatterResult,
} from "@/lib/api-types";

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

  const scatterData =
    timeline.data?.items?.map((item) => ({
      x: new Date(item.fecha_publicacion ?? "").getTime(),
      y: item.importe ?? 0,
      z: item.importe ?? 0,
      titulo: item.titulo ?? "",
      estado: item.estado ?? "",
      fill: getEstadoChartColor(item.estado),
    })) ?? [];

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
      <section className="tf-card-shadow relative overflow-hidden rounded-xl border border-border bg-card/70 p-5">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary/10 via-transparent to-transparent"
        />
        <div className="relative flex items-start justify-between gap-4">
          <div>
            <h1 className="tf-h1">Resumen</h1>
            <p className="text-muted-foreground">
              Qué requiere tu atención hoy en el mercado.
            </p>
          </div>
          <ExportPopover />
        </div>
        <CopilotBar className="relative mt-4 max-w-2xl" />
      </section>

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

      <AtajosAnalisis />
    </div>
  );
}
