"use client";
import { EmptyState } from "@/components/ui/empty-state";

import React, { useState, useMemo, useCallback } from "react";
import dynamic from "next/dynamic";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useSortToggle } from "@/hooks/use-sort-toggle";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import { KpiCard } from "@/components/charts/kpi-card";
const RadarChart = dynamic(() => import("@/components/charts/radar-chart").then((m) => ({ default: m.RadarChart })), {
  ssr: false,
  loading: () => <Skeleton className="h-[420px] w-full rounded-md" />,
});
const CompetitorsBarChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsBarChart })),
  { ssr: false, loading: () => <Skeleton className="h-[500px] w-full rounded-md" /> },
);
const CompetitorsPieChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsPieChart })),
  { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> },
);
const CompetitorsScatterChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsScatterChart })),
  { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> },
);
const CompetitorsTreemap = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsTreemap })),
  { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> },
);
const CompetitorsPositioningChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsPositioningChart })),
  { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> },
);
const CompetitorsEstacionalidadChart = dynamic(
  () => import("@/components/charts/competitors-charts").then((m) => ({ default: m.CompetitorsEstacionalidadChart })),
  { ssr: false, loading: () => <Skeleton className="h-[300px] w-full rounded-md" /> },
);
import { ExportPopover } from "@/components/export-popover";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Stagger } from "@/components/motion";

import { formatCurrency, formatNumber, formatPercent, truncate } from "@/lib/utils";
import { CompanyQuickView } from "@/components/competitors/company-quick-view";
import type { CompanyAwardsData, CompanyProfileData } from "@/components/competitors/company-profile-types";
import { useFilters } from "@/lib/filters";
import { toggleValue } from "@/lib/chart-interaction";
import type { ScatterPoint } from "@/components/charts/competitors-charts";
import {
  Hash,
  Target,
  AlertTriangle,
  Crown,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Search,
  Users,
  TrendingDown,
} from "lucide-react";

interface Competitor {
  nombre: string;
  empresa_id?: number;
  nif?: string;
  count: number;
  importe: number;
  cuota: number;
  contratos_por_anio?: number;
  importe_medio?: number;
  baja_media?: number;
  n_organos?: number;
  ofertas_medias?: number;
  pct_monopolio?: number;
  pct_top_organo?: number;
  ultima?: string;
}

interface HeatmapEntry {
  ccaa: string;
  empresa: string;
  count: number;
}

interface BajaItem {
  grupo: string;
  grupo_id?: number;
  contratos: number;
  baja_media_pct: number | null;
}

interface CompetitorsData {
  total_adjudicaciones: number;
  total_empresas?: number;
  importe_total?: number;
  hhi: number;
  pct_oferta_unica: number;
  pct_pyme: number;
  top_competidor: string;
  competitors: Competitor[];
  scatter_data?: ScatterPoint[];
  heatmap_ccaa?: HeatmapEntry[];
  estacionalidad?: { mes: number; count: number; importe: number }[];
}

type SortKey =
  | "nombre"
  | "count"
  | "importe"
  | "cuota"
  | "contratos_por_anio"
  | "importe_medio"
  | "baja_media"
  | "nif"
  | "ofertas_medias"
  | "pct_monopolio"
  | "pct_top_organo"
  | "ultima";

const MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

// Heatmap color scale
function heatColor(value: number, max: number): string {
  if (max === 0) return "transparent";
  const intensity = value / max;
  const alpha = Math.max(0.08, intensity);
  return `hsl(var(--primary) / ${alpha})`;
}

export default function CompetidoresPage() {
  const { data, isLoading, error } = useFilteredQuery<CompetitorsData>(
    ["analytics", "competitors"],
    "/api/v1/analytics/competitors",
    { staleTime: 5 * 60 * 1000 },
    { limit: "100" },
  );

  // Ranking de bajas por empresa (quién oferta más agresivo). Honra ccaa global
  // vía useFilteredQuery; el endpoint ignora el resto de filtros.
  const { data: bajasData } = useFilteredQuery<{ items: BajaItem[] }>(
    ["competitive", "bajas-empresa"],
    "/api/v1/competitive/bajas",
    { staleTime: 5 * 60 * 1000 },
    { group_by: "empresa", min_contratos: "5", limit: "15" },
  );

  const queryClient = useQueryClient();
  const { data: watchlist } = useQuery<{ items: { empresa_id: number }[] }>({
    queryKey: ["watchlist-empresas"],
    queryFn: () => fetchWithAuth("/api/v1/competitive/watchlist"),
    staleTime: 60 * 1000,
  });
  const watchedIds = useMemo(() => new Set((watchlist?.items ?? []).map((w) => w.empresa_id)), [watchlist]);
  const toggleWatch = useMutation({
    mutationFn: async (e: { empresa_id: number; watched: boolean }) =>
      e.watched
        ? apiMutate("DELETE", `/api/v1/competitive/watchlist/${e.empresa_id}`)
        : apiMutate("POST", "/api/v1/competitive/watchlist", {
            empresa_id: e.empresa_id,
            frequency: "daily",
          }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["watchlist-empresas"] }),
  });

  const [search, setSearch] = useState("");
  const { ccaas, setCcaas } = useFilters();
  const activeCcaa = useMemo(() => new Set(ccaas), [ccaas]);
  const toggleCcaa = useCallback((ccaa: string) => setCcaas(toggleValue(ccaa, ccaas)), [ccaas, setCcaas]);
  const { sortKey, sortDir, toggleSort } = useSortToggle<SortKey>("count");
  const [selectedCompanies, setSelectedCompanies] = useState<string[]>([]);
  const [drillDownCompany, setDrillDownCompany] = useState<Competitor | null>(null);
  const drillDownCompanyId = drillDownCompany?.empresa_id;
  const { data: drillDownProfile, isLoading: isLoadingDrillDownProfile } = useFilteredQuery<CompanyProfileData>(
    ["competitive-company-profile", String(drillDownCompanyId ?? "none")],
    `/api/v1/competitive/empresas/${drillDownCompanyId ?? 0}/perfil`,
    {
      enabled: drillDownCompanyId != null,
      staleTime: 5 * 60 * 1000,
    },
  );
  const { data: drillDownAwards, isLoading: isLoadingDrillDownAwards } = useFilteredQuery<CompanyAwardsData>(
    ["competitive-company-awards-preview", String(drillDownCompanyId ?? "none")],
    `/api/v1/competitive/empresas/${drillDownCompanyId ?? 0}/adjudicaciones`,
    {
      enabled: drillDownCompanyId != null,
      staleTime: 5 * 60 * 1000,
    },
    { limit: "5", offset: "0", sort: "fecha_desc" },
  );

  const toggleCompareSelection = useCallback((nombre: string) => {
    setSelectedCompanies((prev) => {
      if (prev.includes(nombre)) return prev.filter((n) => n !== nombre);
      if (prev.length >= 2) return [prev[1], nombre];
      return [...prev, nombre];
    });
  }, []);

  // Apply search filter to all data
  const searchFilter = useCallback(
    (items: { nombre: string }[]) => {
      if (!search) return items;
      const q = search.toLowerCase();
      return items.filter((c) => c.nombre.toLowerCase().includes(q));
    },
    [search],
  );

  const filteredCompetitors = useMemo(() => {
    if (!data?.competitors) return [];
    return searchFilter(data.competitors) as Competitor[];
  }, [data, searchFilter]);

  const filteredSorted = useMemo(() => {
    return [...filteredCompetitors].sort((a, b) => {
      const mul = sortDir === "asc" ? 1 : -1;
      if (sortKey === "nombre" || sortKey === "nif" || sortKey === "ultima") {
        return mul * ((a[sortKey] ?? "") as string).localeCompare((b[sortKey] ?? "") as string);
      }
      return mul * (((a[sortKey] as number) ?? 0) - ((b[sortKey] as number) ?? 0));
    });
  }, [filteredCompetitors, sortKey, sortDir]);

  // Pie chart: top 10 + Otros by importe (filtered)
  const pieData = useMemo(() => {
    if (!filteredCompetitors.length) return [];
    const sorted = [...filteredCompetitors].sort((a, b) => b.importe - a.importe);
    const top10 = sorted.slice(0, 10);
    const top10Importe = top10.reduce((s, c) => s + c.importe, 0);
    // Sin búsqueda, "Otros" = mercado total − top 10 (incluye la cola fuera de
    // los `limit` competidores devueltos). Con búsqueda, solo lo filtrado visible.
    const otrosImporte = search
      ? sorted.slice(10).reduce((s, c) => s + c.importe, 0)
      : Math.max((data?.importe_total ?? top10Importe) - top10Importe, 0);
    const result = top10.map((c) => ({ name: truncate(c.nombre, 25), value: c.importe }));
    if (otrosImporte > 0) result.push({ name: "Otros", value: otrosImporte });
    return result;
  }, [filteredCompetitors, search, data]);

  // Top 20 bar chart data (filtered)
  const barData = useMemo(() => {
    return [...filteredCompetitors].sort((a, b) => b.count - a.count).slice(0, 20);
  }, [filteredCompetitors]);

  // Scatter data filtered
  const scatterData = useMemo(() => {
    if (!data?.scatter_data) return [];
    return searchFilter(data.scatter_data) as ScatterPoint[];
  }, [data, searchFilter]);

  // Top 5 for scatter labels
  const scatterTop5 = useMemo(() => {
    if (!data?.competitors) return new Set<string>();
    const top = [...data.competitors].sort((a, b) => b.importe - a.importe).slice(0, 5);
    return new Set(top.map((c) => c.nombre));
  }, [data]);

  // Heatmap
  const heatmapData = useMemo(() => {
    if (!data?.heatmap_ccaa?.length)
      return {
        empresas: [] as string[],
        ccaas: [] as string[],
        matrix: {} as Record<string, Record<string, number>>,
        max: 0,
      };
    const filtered = search
      ? data.heatmap_ccaa.filter((h) => h.empresa.toLowerCase().includes(search.toLowerCase()))
      : data.heatmap_ccaa;

    // Top 10 empresas by total count
    const empresaCounts: Record<string, number> = {};
    for (const h of filtered) {
      empresaCounts[h.empresa] = (empresaCounts[h.empresa] ?? 0) + h.count;
    }
    const empresas = Object.entries(empresaCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([e]) => e);
    const empresaSet = new Set(empresas);

    const ccaaSet = new Set<string>();
    const matrix: Record<string, Record<string, number>> = {};
    let max = 0;
    for (const h of filtered) {
      if (!empresaSet.has(h.empresa)) continue;
      ccaaSet.add(h.ccaa);
      if (!matrix[h.empresa]) matrix[h.empresa] = {};
      matrix[h.empresa][h.ccaa] = h.count;
      if (h.count > max) max = h.count;
    }
    return { empresas, ccaas: Array.from(ccaaSet).sort(), matrix, max };
  }, [data, search]);

  // Radar comparison data
  const radarData = useMemo(() => {
    if (selectedCompanies.length !== 2 || !data?.competitors) return null;
    const [nameA, nameB] = selectedCompanies;
    const compA = data.competitors.find((c) => c.nombre === nameA);
    const compB = data.competitors.find((c) => c.nombre === nameB);
    if (!compA || !compB) return null;

    const allComps = data.competitors;
    const maxCount = Math.max(...allComps.map((c) => c.count), 1);
    const maxImporte = Math.max(...allComps.map((c) => c.importe), 1);
    const maxCuota = Math.max(...allComps.map((c) => c.cuota), 1);
    const maxCpa = Math.max(...allComps.map((c) => c.contratos_por_anio ?? 0), 1);
    const maxIm = Math.max(...allComps.map((c) => c.importe_medio ?? 0), 1);
    const maxBaja = Math.max(...allComps.map((c) => c.baja_media ?? 0), 1);

    const dims = ["Contratos", "Importe", "Cuota", "Contratos/Año", "Importe Medio", "Agresividad baja"];
    const normalize = (c: Competitor) => [
      (c.count / maxCount) * 100,
      (c.importe / maxImporte) * 100,
      (c.cuota / maxCuota) * 100,
      ((c.contratos_por_anio ?? 0) / maxCpa) * 100,
      ((c.importe_medio ?? 0) / maxIm) * 100,
      ((c.baja_media ?? 0) / maxBaja) * 100,
    ];

    const valsA = normalize(compA);
    const valsB = normalize(compB);

    return {
      nameA,
      nameB,
      dataA: dims.map((d, i) => ({ dimension: d, value: valsA[i] })),
      dataB: dims.map((d, i) => ({ dimension: d, value: valsB[i] })),
    };
  }, [selectedCompanies, data]);

  // Treemap: top 20 companies by importe for sector visualization
  const treemapData = useMemo(() => {
    if (!filteredCompetitors.length) return [];
    return [...filteredCompetitors]
      .sort((a, b) => b.importe - a.importe)
      .slice(0, 20)
      .map((c) => ({
        name: truncate(c.nombre, 22),
        size: c.importe,
        count: c.count,
      }));
  }, [filteredCompetitors]);

  // Positioning scatter: baja_media vs importe_medio
  const positioningData = useMemo(() => {
    if (!filteredCompetitors.length) return [];
    return filteredCompetitors
      .filter((c) => c.baja_media != null && c.importe_medio != null && c.importe_medio > 0)
      .map((c) => ({
        nombre: c.nombre,
        baja_media: c.baja_media ?? 0,
        importe_medio: c.importe_medio ?? 0,
        count: c.count,
        pct_monopolio: c.pct_monopolio ?? 0,
      }));
  }, [filteredCompetitors]);

  // Estacionalidad monthly chart data
  const estacionalidadData = useMemo(() => {
    if (!data?.estacionalidad?.length) return [];
    const full = Array.from({ length: 12 }, (_, i) => {
      const entry = data.estacionalidad!.find((e) => e.mes === i + 1);
      return { mes: MONTH_LABELS[i], count: entry?.count ?? 0, importe: entry?.importe ?? 0 };
    });
    return full;
  }, [data]);

  // Desglose por CCAA de la empresa desde su PERFIL (por_ccaa, por empresa,
  // completo hasta 20 CCAA), no del heatmap_ccaa global recortado al top-10
  // empresas — que dejaba el drill-down VACÍO para cualquier empresa fuera de
  // ese top, prometiendo más de lo que entregaba (ADR-014).
  // Ranking de bajas por empresa (más agresivas primero)
  const bajasSorted = useMemo(() => {
    const items = (bajasData?.items ?? []).filter((b) => b.baja_media_pct != null);
    const sorted = [...items].sort((a, b) => (b.baja_media_pct ?? 0) - (a.baja_media_pct ?? 0));
    const maxBaja = Math.max(...sorted.map((b) => b.baja_media_pct ?? 0), 1);
    return { rows: sorted.slice(0, 12), maxBaja };
  }, [bajasData]);

  if (error) {
    return (
      <div className="border-destructive/50 bg-destructive/10 rounded-lg border p-6 text-center" role="alert">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  const TABLE_COLUMNS: { key: SortKey; label: string }[] = [
    { key: "nombre", label: "Nombre" },
    { key: "nif", label: "NIF" },
    { key: "count", label: "Adjudicaciones" },
    { key: "importe", label: "Importe" },
    { key: "cuota", label: "Cuota %" },
    { key: "contratos_por_anio", label: "Contratos/Año" },
    { key: "importe_medio", label: "Importe Medio" },
    { key: "baja_media", label: "Baja Media %" },
    { key: "ofertas_medias", label: "Ofertas Medias" },
    { key: "pct_monopolio", label: "% Sin comp." },
    { key: "pct_top_organo", label: "% Top Organo" },
    { key: "ultima", label: "Ultima Adj." },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Competidores</h1>
          <p className="text-muted-foreground">Cuota de mercado de empresas competidoras.</p>
        </div>
        <div className="flex items-center gap-3">
          <SearchAutocomplete
            className="w-full sm:w-72"
            placeholder="Buscar empresa..."
            value={search}
            onChange={setSearch}
            suggestions={data?.competitors?.map((c) => c.nombre) ?? []}
            leftIcon={<Search className="h-4 w-4" />}
            inputClassName="pl-9"
          />
          <ExportPopover extraParams={{ section: "competitors" }} />
        </div>
      </div>

      {/* KPI Row */}
      <Stagger className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stagger.Item>
          <KpiCard
            title="Total Adjudicaciones"
            value={isLoading ? undefined : formatNumber(data?.total_adjudicaciones)}
            icon={Hash}
            loading={isLoading}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="HHI Concentracion"
            value={isLoading ? undefined : formatNumber(data?.hhi)}
            subtitle={
              data?.hhi != null
                ? data.hhi < 1500
                  ? "Mercado competitivo"
                  : data.hhi < 2500
                    ? "Concentracion moderada"
                    : "Mercado concentrado"
                : undefined
            }
            icon={Target}
            loading={isLoading}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="% Oferta Unica"
            value={isLoading ? undefined : formatPercent(data?.pct_oferta_unica)}
            subtitle="Licitaciones con un solo ofertante"
            icon={AlertTriangle}
            loading={isLoading}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="Top Competidor"
            value={isLoading ? undefined : truncate(data?.top_competidor ?? data?.competitors?.[0]?.nombre ?? "-", 30)}
            icon={Crown}
            loading={isLoading}
          />
        </Stagger.Item>
      </Stagger>

      {/* Charts Row 1: Bar + Pie */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Horizontal Bar: Top 20 by count */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top 20 Competidores (por adjudicaciones)</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[500px] w-full" />
            ) : barData.length > 0 ? (
              <ChartErrorBoundary>
                <CompetitorsBarChart data={barData} />
              </ChartErrorBoundary>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        {/* Pie: Market share by importe */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Cuota de Mercado por Importe (Top 10)</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : pieData.length > 0 ? (
              <ChartErrorBoundary>
                <CompetitorsPieChart data={pieData} />
              </ChartErrorBoundary>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Charts Row 2: Scatter + Heatmap */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Scatter: ticket_medio vs n_organos */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Ticket Medio vs Dependencia de Clientes</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : scatterData.length > 0 ? (
              <ChartErrorBoundary>
                <CompetitorsScatterChart data={scatterData} top5Names={scatterTop5} />
              </ChartErrorBoundary>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        {/* CCAA x Empresa Heatmap */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Actividad por CCAA y Empresa</CardTitle>
            <p className="text-muted-foreground text-xs">Clic en una CCAA para filtrar</p>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : heatmapData.empresas.length > 0 ? (
              <div className="overflow-x-auto">
                <div
                  className="grid gap-px text-xs"
                  style={{
                    gridTemplateColumns: `180px repeat(${heatmapData.ccaas.length}, minmax(50px, 1fr))`,
                  }}
                >
                  {/* Header row */}
                  <div className="text-muted-foreground p-1 font-medium" />
                  {heatmapData.ccaas.map((ccaa) => (
                    <button
                      key={ccaa}
                      type="button"
                      onClick={() => toggleCcaa(ccaa)}
                      aria-pressed={activeCcaa.has(ccaa)}
                      className={`hover:bg-muted cursor-pointer truncate rounded-sm p-1 text-center font-medium transition-colors ${activeCcaa.has(ccaa) ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}
                      title={`Filtrar por ${ccaa}`}
                    >
                      {truncate(ccaa, 10)}
                    </button>
                  ))}
                  {/* Data rows */}
                  {heatmapData.empresas.map((empresa) => (
                    <React.Fragment key={empresa}>
                      <div key={`label-${empresa}`} className="truncate p-1 font-medium" title={empresa}>
                        {truncate(empresa, 25)}
                      </div>
                      {heatmapData.ccaas.map((ccaa) => {
                        const val = heatmapData.matrix[empresa]?.[ccaa] ?? 0;
                        return (
                          <div
                            key={`${empresa}-${ccaa}`}
                            className="cursor-default rounded-sm p-1 text-center transition-colors"
                            style={{ backgroundColor: heatColor(val, heatmapData.max) }}
                            title={`${empresa} - ${ccaa}: ${val}`}
                          >
                            {val > 0 ? val : ""}
                          </div>
                        );
                      })}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Charts Row 3: Treemap + Top 5 Metrics */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Cuota de Mercado (Treemap Top 20)</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : treemapData.length > 0 ? (
              <ChartErrorBoundary>
                <CompetitorsTreemap data={treemapData} />
              </ChartErrorBoundary>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Posicionamiento Competitivo</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : positioningData.length > 0 ? (
              <ChartErrorBoundary>
                <CompetitorsPositioningChart data={positioningData} />
              </ChartErrorBoundary>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Estacionalidad Mensual */}
      {estacionalidadData.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Estacionalidad del mercado (filtrado)</CardTitle>
          </CardHeader>
          <CardContent>
            <ChartErrorBoundary>
              <CompetitorsEstacionalidadChart data={estacionalidadData} />
            </ChartErrorBoundary>
          </CardContent>
        </Card>
      )}

      {/* Bajas por empresa: quién oferta más agresivo */}
      {bajasSorted.rows.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingDown className="h-4 w-4" />
              Empresas mas agresivas en precio (baja media)
            </CardTitle>
            <p className="text-muted-foreground mt-1 text-xs">
              Ambito: respeta el filtro de CCAA; no aplica rango de fechas, CPV ni importe.
            </p>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              {bajasSorted.rows.map((b) => (
                <div key={b.grupo_id ?? b.grupo} className="flex items-center gap-2 text-sm">
                  <span className="w-48 truncate" title={b.grupo}>
                    {truncate(b.grupo, 32)}
                  </span>
                  <div className="bg-muted h-4 flex-1 overflow-hidden rounded-full">
                    <div
                      className="bg-primary h-full rounded-full"
                      style={{ width: `${((b.baja_media_pct ?? 0) / bajasSorted.maxBaja) * 100}%` }}
                    />
                  </div>
                  <span className="w-14 text-right text-xs tabular-nums">{formatPercent(b.baja_media_pct ?? 0)}</span>
                  <span className="text-muted-foreground w-10 text-right text-xs tabular-nums">
                    {formatNumber(b.contratos)}
                  </span>
                </div>
              ))}
            </div>
            <p className="text-muted-foreground mt-3 text-xs">
              Baja media = (presupuesto − adjudicado) / presupuesto, sobre empresas con ≥ 5 contratos. La cifra gris es
              el nº de contratos.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Radar Comparator */}
      {radarData && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Users className="h-4 w-4" />
              Comparacion: {truncate(radarData.nameA, 25)} vs {truncate(radarData.nameB, 25)}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <RadarChart
              data={radarData.dataA}
              name={truncate(radarData.nameA, 20)}
              compareData={radarData.dataB}
              compareName={truncate(radarData.nameB, 20)}
              height={400}
            />
          </CardContent>
        </Card>
      )}

      {selectedCompanies.length > 0 && selectedCompanies.length < 2 && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-300">
          Selecciona 1 empresa mas en la tabla para comparar con radar. ({selectedCompanies.length}/2 seleccionadas)
        </div>
      )}

      {/* Table */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle className="text-base">Todos los Competidores</CardTitle>
            <p className="text-muted-foreground text-xs">Selecciona 2 empresas para comparar con radar</p>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : filteredSorted.length > 0 ? (
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="text-muted-foreground border-b text-left">
                    <TableHead className="w-10 px-2 py-2 font-medium">
                      <span className="sr-only">Comparar</span>
                    </TableHead>
                    {TABLE_COLUMNS.map(({ key, label }) => (
                      <TableHead
                        key={key}
                        className="hover:text-foreground cursor-pointer px-3 py-2 font-medium whitespace-nowrap select-none"
                        tabIndex={0}
                        role="columnheader"
                        aria-sort={sortKey === key ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                        onClick={() => toggleSort(key)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") toggleSort(key);
                        }}
                      >
                        <span className="inline-flex items-center gap-1">
                          {label}
                          {sortKey === key ? (
                            sortDir === "asc" ? (
                              <ArrowUp className="text-primary h-3 w-3" />
                            ) : (
                              <ArrowDown className="text-primary h-3 w-3" />
                            )
                          ) : (
                            <ArrowUpDown className="h-3 w-3 opacity-40" />
                          )}
                        </span>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredSorted.map((c, idx) => (
                    <TableRow key={c.nif ?? c.nombre ?? idx} className="hover:bg-muted/50 border-b last:border-0">
                      <TableCell className="px-2 py-2">
                        <Checkbox
                          className="h-5 w-5"
                          checked={selectedCompanies.includes(c.nombre)}
                          onCheckedChange={() => toggleCompareSelection(c.nombre)}
                        />
                      </TableCell>
                      <TableCell
                        className="text-primary cursor-pointer px-3 py-2 font-medium hover:underline"
                        onClick={() => setDrillDownCompany(c)}
                      >
                        {c.nombre}
                      </TableCell>
                      <TableCell className="text-muted-foreground px-3 py-2 tabular-nums">{c.nif ?? "-"}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{formatNumber(c.count)}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{formatCurrency(c.importe)}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">{formatPercent(c.cuota)}</TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">
                        {c.contratos_por_anio != null ? formatNumber(c.contratos_por_anio) : "-"}
                      </TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">
                        {c.importe_medio != null ? formatCurrency(c.importe_medio) : "-"}
                      </TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">
                        {c.baja_media != null ? formatPercent(c.baja_media) : "-"}
                      </TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">
                        {c.ofertas_medias != null ? c.ofertas_medias.toFixed(1) : "-"}
                      </TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">
                        {c.pct_monopolio != null ? formatPercent(c.pct_monopolio) : "-"}
                      </TableCell>
                      <TableCell className="px-3 py-2 tabular-nums">
                        {c.pct_top_organo != null ? formatPercent(c.pct_top_organo) : "-"}
                      </TableCell>
                      <TableCell className="text-muted-foreground px-3 py-2 tabular-nums">{c.ultima ?? "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="text-muted-foreground py-8 text-center">
              {search ? "No se encontraron competidores" : "Sin datos disponibles"}
            </p>
          )}
          {!isLoading && filteredSorted.length > 0 && (
            <>
              <Separator className="my-3" />
              <p className="text-muted-foreground text-xs">
                Mostrando {filteredSorted.length} de {data?.total_empresas ?? data?.competitors.length ?? 0}{" "}
                competidores
              </p>
            </>
          )}
        </CardContent>
      </Card>

      {/* Drill-down Sheet */}
      <Sheet open={!!drillDownCompany} onOpenChange={(open) => !open && setDrillDownCompany(null)}>
        <SheetContent className="flex flex-col overflow-hidden p-0 sm:max-w-2xl lg:max-w-3xl">
          {drillDownCompany && drillDownCompanyId != null ? (
            <CompanyQuickView
              empresaId={drillDownCompanyId}
              company={drillDownCompany}
              profile={drillDownProfile}
              recentAwards={drillDownAwards}
              isLoadingProfile={isLoadingDrillDownProfile}
              isLoadingAwards={isLoadingDrillDownAwards}
              watched={watchedIds.has(drillDownCompanyId)}
              watchPending={toggleWatch.isPending}
              onToggleWatch={() =>
                toggleWatch.mutate({
                  empresa_id: drillDownCompanyId,
                  watched: watchedIds.has(drillDownCompanyId),
                })
              }
            />
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}
