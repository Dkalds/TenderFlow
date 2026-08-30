"use client";

/**
 * Vista compartida por la ruta `/proyectos-modulos` y por `?vista=proyectos` del
 * espacio Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo
 * no vive en el `page.tsx` de la ruta.
 */

import { EmptyState } from "@/components/ui/empty-state";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
const ModulosBarChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.ModulosBarChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const TiposPieChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.TiposPieChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const ModulosTreemap = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.ModulosTreemap })), { ssr: false, loading: () => <Skeleton className="h-[350px] w-full rounded-md" /> });
const TiposTreemap = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.TiposTreemap })), { ssr: false, loading: () => <Skeleton className="h-[350px] w-full rounded-md" /> });
const TipoEstadoStackedChart = dynamic(() => import("@/components/charts/proyectos-modulos-charts").then(m => ({ default: m.TipoEstadoStackedChart })), { ssr: false, loading: () => <Skeleton className="h-[360px] w-full rounded-md" /> });
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { ExportPopover } from "@/components/export-popover";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { valorOEmpty } from "@/lib/cobertura";
import type { Schemas } from "@/lib/api-types";
import {
  FolderKanban,
  Hash,
  Boxes,
  Layers,
  DollarSign,
  TrendingUp,
  Percent,
  ArrowUpDown,
} from "lucide-react";

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
type ProyectosModulosResponse = Schemas["ProyectosModulosResult"] & {
  total?: number;
  menciones_modulo?: number;
  pct_match_portfolio?: number;
  modulos_por_clasificada?: number;
};

/** Sentinel used by the backend to flag a brand-new module (no prior-year data). */
const YOY_NUEVO = 999;


type ModSortKey = "modulo" | "count" | "importe" | "importe_medio";

export default function ProyectosModulosView() {
  const [modSortKey, setModSortKey] = useState<ModSortKey>("count");
  const [modSortDir, setModSortDir] = useState<"asc" | "desc">("desc");

  const { data, isLoading, error } =
    useFilteredQuery<ProyectosModulosResponse>(
      ["analytics", "proyectos-modulos"],
      "/api/v1/analytics/proyectos-modulos",
      { staleTime: 5 * 60 * 1000 },
    );

  const modulos = useMemo(() => data?.modulos ?? [], [data]);
  const tipos = useMemo(() => data?.tipos_proyecto ?? [], [data]);

  // SAP-specific KPIs — a nivel licitación distinct desde el backend, NO la suma
  // de filas de módulo (una licitación con módulos A+B contaba doble el importe).
  // `?? null`: sin dato la tarjeta se abstiene. Un "0 €" de ticket medio
  // afirma que los contratos SAP no valen nada.
  const ticketMedioSAP = data?.ticket_medio_sap ?? null;

  // Los dos ratios y sus denominadores vienen calculados del backend (ADR-014):
  // aquí no se derivan totales. `?? null` para que la tarjeta se abstenga ("—")
  // si el campo no viaja, en vez de inventar un 0 %.
  const totalAmbito = data?.total ?? null;
  const totalClasificados = data?.total_clasificados ?? 0;
  const mencionesModulo = data?.menciones_modulo ?? null;
  const modulosPorClasificada = data?.modulos_por_clasificada ?? null;
  const pctMatchPortfolio = data?.pct_match_portfolio ?? null;

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

  const yoy = data?.top_modulo_yoy ?? null;
  const cpvRows = data?.cpv ?? [];

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
      .slice(0, 12) as Array<{ tipo: string; [estado: string]: number | string }>;
  }, [data]);

  // Average importe per module table
  const modulosWithAvg = useMemo(() => {
    return modulos.map((m) => ({
      ...m,
      importe_medio: m.count > 0 ? m.importe / m.count : 0,
    }));
  }, [modulos]);

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

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="sr-only">
            Proyectos &amp; Módulos
          </h1>
          <p className="text-muted-foreground">
            Desglose por tipo de proyecto y módulo SAP.
          </p>
        </div>
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ section: "proyectos-modulos" }}
        />
      </div>

      {/* SAP-specific KPI Row */}
      <KpiStrip columns={5}>
        <KpiCard
          title="Ticket Medio SAP"
          value={isLoading ? undefined : valorOEmpty(ticketMedioSAP, formatCurrency)}
          icon={DollarSign}
          loading={isLoading}
        />
        <KpiCard
          title="Top módulo YoY"
          value={isLoading ? undefined : (yoy?.modulo ?? "-")}
          subtitle={
            yoy && yoy.crecimiento_pct >= YOY_NUEVO
              ? `NUEVO · ${formatNumber(yoy.n_act)} lics`
              : undefined
          }
          trend={yoy && yoy.crecimiento_pct < YOY_NUEVO ? yoy.crecimiento_pct : undefined}
          trendLabel={
            yoy && yoy.crecimiento_pct < YOY_NUEVO
              ? `${formatNumber(yoy.n_act)} lics`
              : undefined
          }
          icon={TrendingUp}
          loading={isLoading}
        />
        {/*
          Intensidad multi-módulo con el signo correcto: 1,00 = todas las
          clasificadas tienen un solo módulo, y sube al detectarse más módulos
          por licitación. NO es un «% de licitaciones multi-módulo»: eso exige
          contar licitaciones con >1 módulo distinto, que el agregado SQL de hoy
          (un COUNT por patrón, sin distinct por licitación) no produce.
        */}
        <KpiCard
          title="Módulos por clasificada"
          value={
            isLoading || modulosPorClasificada == null
              ? undefined
              : formatNumber(modulosPorClasificada)
          }
          subtitle={
            mencionesModulo != null
              ? `${formatNumber(mencionesModulo)} menciones / ${formatNumber(totalClasificados)} clasificadas`
              : undefined
          }
          icon={Percent}
          loading={isLoading}
        />
        <KpiCard
          title="Ticket S/4HANA"
          value={
            isLoading
              ? undefined
              : ticketS4Hana !== null
                ? formatCurrency(ticketS4Hana)
                : "N/A"
          }
          icon={Boxes}
          loading={isLoading}
        />
        <KpiCard
          title="% Match Portfolio"
          value={
            isLoading || pctMatchPortfolio == null
              ? undefined
              : formatPercent(pctMatchPortfolio)
          }
          subtitle={
            totalAmbito != null
              ? `${formatNumber(totalClasificados)} / ${formatNumber(totalAmbito)} licitaciones del ámbito`
              : undefined
          }
          icon={Layers}
          loading={isLoading}
        />
      </KpiStrip>

      {/* Original KPIs */}
      <KpiStrip columns={3}>
        <KpiCard
          title="Total Clasificados"
          value={isLoading ? undefined : formatNumber(totalClasificados)}
          subtitle={
            totalAmbito != null
              ? `de ${formatNumber(totalAmbito)} del ámbito`
              : undefined
          }
          icon={Hash}
          loading={isLoading}
        />
        {/*
          `modulos` / `tipos_proyecto` llegan completos (sin recorte), así que
          su longitud ES el conteo. Antes se anteponía `data?.total_modulos` /
          `data?.total_tipos`, campos que el contrato no emite.
        */}
        <KpiCard
          title="Módulos Detectados"
          value={isLoading ? undefined : formatNumber(modulos.length)}
          icon={Boxes}
          loading={isLoading}
        />
        <KpiCard
          title="Tipos de Proyecto"
          value={isLoading ? undefined : formatNumber(tipos.length)}
          icon={Layers}
          loading={isLoading}
        />
      </KpiStrip>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Bar Chart: SAP Modules */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <FolderKanban className="h-4 w-4" />
              Módulos SAP por Cantidad
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : modulosSorted.length > 0 ? (
              <ModulosBarChart data={modulosSorted} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        {/* Pie Chart: Project Types */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tipos de Proyecto</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : tiposPie.length > 0 ? (
              <TiposPieChart data={tiposPie} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Treemaps: Modulos + Tipos side by side */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Módulos por Importe (Treemap)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[350px] w-full" />
            ) : modulosTreemap.length > 0 ? (
              <ModulosTreemap data={modulosTreemap} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Tipos Proyecto por Importe (Treemap)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[350px] w-full" />
            ) : tiposTreemap.length > 0 ? (
              <TiposTreemap data={tiposTreemap} />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Tipo de proyecto x Estado (stacked) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tipo de proyecto x Estado</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[360px] w-full" />
          ) : tipoEstadoData.length > 0 ? (
            <TipoEstadoStackedChart data={tipoEstadoData} estados={tipoEstadoEstados} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* Average Importe per Module Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Importe Medio por Módulo SAP
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    {(
                      [
                        ["modulo", "Módulo"],
                        ["count", "Cantidad"],
                        ["importe", "Importe Total"],
                        ["importe_medio", "Importe Medio"],
                      ] as [ModSortKey, string][]
                    ).map(([key, label]) => (
                      <th
                        key={key}
                        className={`pb-2 pr-4 font-medium text-muted-foreground ${key !== "modulo" ? "text-right" : ""}`}
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-auto p-0 font-medium text-muted-foreground hover:text-foreground"
                          onClick={() => toggleModSort(key)}
                        >
                          {label}
                          <ArrowUpDown className="ml-1 h-3 w-3" />
                        </Button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sortedModulosAvg.map((item, idx) => (
                    <tr
                      key={idx}
                      className="border-b border-border/50 hover:bg-muted/50"
                    >
                      <td className="py-2 pr-4 font-medium">{item.modulo}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(item.count)}
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {formatCurrency(item.importe)}
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {formatCurrency(item.importe_medio)}
                      </td>
                    </tr>
                  ))}
                  {sortedModulosAvg.length === 0 && (
                    <tr>
                      <td
                        colSpan={4}
                        className="py-8 text-center text-muted-foreground"
                      >
                        Sin datos
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Project Types Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tipos de Proyecto</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-2 pr-4 font-medium text-muted-foreground">
                      Tipo
                    </th>
                    <th className="pb-2 pr-4 font-medium text-muted-foreground text-right">
                      Cantidad
                    </th>
                    <th className="pb-2 font-medium text-muted-foreground text-right">
                      Importe
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[...tipos]
                    .sort((a, b) => b.count - a.count)
                    .map((item, idx) => (
                      <tr
                        key={idx}
                        className="border-b border-border/50 hover:bg-muted/50"
                      >
                        <td className="py-2 pr-4 font-medium">{item.tipo}</td>
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {formatNumber(item.count)}
                        </td>
                        <td className="py-2 text-right tabular-nums">
                          {formatCurrency(item.importe)}
                        </td>
                      </tr>
                    ))}
                  {tipos.length === 0 && (
                    <tr>
                      <td
                        colSpan={3}
                        className="py-8 text-center text-muted-foreground"
                      >
                        Sin datos
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Top CPV codes */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top códigos CPV</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-2 pr-4 font-medium text-muted-foreground">CPV</th>
                    <th className="pb-2 pr-4 text-right font-medium text-muted-foreground">
                      Licitaciones
                    </th>
                    <th className="pb-2 text-right font-medium text-muted-foreground">
                      Importe
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {cpvRows.map((item) => (
                    <tr
                      key={item.cpv}
                      className="border-b border-border/50 hover:bg-muted/50"
                    >
                      <td className="py-2 pr-4">
                        <span className="block max-w-md truncate" title={item.cpv_desc}>
                          {item.cpv_desc}
                        </span>
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {formatNumber(item.count)}
                      </td>
                      <td className="py-2 text-right tabular-nums">
                        {formatCurrency(item.importe)}
                      </td>
                    </tr>
                  ))}
                  {cpvRows.length === 0 && (
                    <tr>
                      <td colSpan={3} className="py-8 text-center text-muted-foreground">
                        Sin datos
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
