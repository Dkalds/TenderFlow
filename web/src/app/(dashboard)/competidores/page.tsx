"use client";
import { EmptyState } from "@/components/ui/empty-state";
import { Panel, PanelTabs } from "@/components/console/panel";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import React, { startTransition, useState, useMemo, useCallback } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
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
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { Separator } from "@/components/ui/separator";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Stagger } from "@/components/motion";

import { formatCurrency, formatNumber, formatPercent, truncate } from "@/lib/utils";
import { celdaSaludPorPct, valorOEmpty } from "@/lib/cobertura";
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
  X,
} from "lucide-react";

import {
  drillDownExtraParams,
  drillDownIds,
  toggleCompareSelection,
  useCompetidoresView,
  type BajaItem,
  type Competitor,
  type HeatmapEntry,
  type SortKey,
} from "./_hooks/use-competidores-view";

interface CompetitorsData {
  total_adjudicaciones: number;
  total_empresas?: number;
  importe_total?: number;
  hhi: number;
  pct_oferta_unica: number;
  /**
   * Qué porcentaje de las adjudicaciones trae el número de ofertantes.
   *
   * Es el denominador de `pct_oferta_unica`, y sin él ese porcentaje no
   * significa nada: `services/analytics/competitors.py` lo calcula solo sobre
   * las licitaciones que reportan el dato («cobertura parcial según fuente»,
   * dice su propio comentario). La API ya lo envía —`shared/dto.py`— y esta
   * pantalla no lo miraba: publicaba el porcentaje a secas mientras `/resumen`,
   * un clic más allá, se abstenía de publicarlo por cobertura insuficiente.
   */
  cobertura_ofertas_pct?: number | null;
  pct_pyme: number;
  top_competidor: string;
  competitors: Competitor[];
  scatter_data?: ScatterPoint[];
  heatmap_ccaa?: HeatmapEntry[];
  estacionalidad?: { mes: number; count: number; importe: number }[];
}

// Heatmap color scale
function heatColor(value: number, max: number): string {
  if (max === 0) return "transparent";
  const intensity = value / max;
  const alpha = Math.max(0.08, intensity);
  return `hsl(var(--primary) / ${alpha})`;
}

interface CompetitorRowProps {
  competitor: Competitor;
  selected: boolean;
  onToggleCompare: (nombre: string) => void;
  onDrillDown: (competitor: Competitor) => void;
}

// Memoizado: evita recalcular formato/derivados y re-renderizar cada fila
// cuando el padre cambia por estado ajeno a la tabla (ej. abrir el drill-down
// del panel lateral), que era la causa del bloqueo largo de INP al hacer clic
// en el nombre de una empresa.
const CompetitorRow = React.memo(function CompetitorRow({
  competitor: c,
  selected,
  onToggleCompare,
  onDrillDown,
}: CompetitorRowProps) {
  const cifs = (c.nifs?.length ?? 0) > 1 ? c.nifs! : c.nif ? [c.nif] : (c.nifs ?? []);
  const variantCount = c.nombres_variantes?.length ?? 0;
  const identityCount = c.empresa_ids?.length ?? 0;
  const groupingLabel =
    cifs.length > 1
      ? `${cifs.length} CIF`
      : variantCount > 1
        ? `${variantCount} nombres`
        : identityCount > 1
          ? `${identityCount} identidades`
          : "Agrupada";
  const groupingDetails = [
    variantCount > 0 ? `${variantCount} variantes de nombre` : null,
    cifs.length > 0 ? `${cifs.length} CIF` : null,
    identityCount > 0 ? `${identityCount} identidades del maestro` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  // El nombre es un botón sólo cuando hay dossier al que ir. En el caso
  // agrupado el tooltip explica que el dossier suma todas las identidades;
  // sin agrupación no hay nada que explicar y el control va desnudo.
  const nombreBoton = (
    <button
      type="button"
      className="text-primary cursor-pointer text-left hover:underline"
      onClick={() => onDrillDown(c)}
    >
      {c.nombre}
    </button>
  );

  return (
    <TableRow className="hover:bg-muted/50 border-b last:border-0">
      <TableCell className="px-2 py-2">
        <Checkbox
          className="h-5 w-5"
          checked={selected}
          onCheckedChange={() => onToggleCompare(c.nombre)}
        />
      </TableCell>
      <TableCell className="px-3 py-2 font-medium">
        <div className="flex min-w-52 items-center gap-2">
          {c.empresa_id != null || (c.empresa_ids?.length ?? 0) > 0 ? (
            c.es_agrupacion ? (
              <Tooltip>
                <TooltipTrigger asChild>{nombreBoton}</TooltipTrigger>
                <TooltipContent>
                  Abrir el dossier agregando todas las identidades del grupo
                </TooltipContent>
              </Tooltip>
            ) : (
              nombreBoton
            )
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <Link
                  href={`/empresas?q=${encodeURIComponent(c.nombre)}`}
                  className="text-primary text-left hover:underline"
                >
                  {c.nombre}
                </Link>
              </TooltipTrigger>
              <TooltipContent className="max-w-64">
                Sin identidad en el maestro de empresas; el dossier individual no está
                disponible. Este enlace la busca en el maestro.
              </TooltipContent>
            </Tooltip>
          )}
          {c.es_agrupacion ? (
            <Tooltip>
              {/* `Badge` no reenvía ref (es una función suelta que escupe un
                  `div`), así que el disparador es el `span`: si el ref no
                  llegara, Radix se quedaría sin ancla y el tooltip flotaría. */}
              <TooltipTrigger asChild>
                <span className="inline-flex shrink-0">
                  <Badge variant="secondary" className="font-normal">
                    {groupingLabel}
                  </Badge>
                </span>
              </TooltipTrigger>
              <TooltipContent>{groupingDetails}</TooltipContent>
            </Tooltip>
          ) : null}
        </div>
      </TableCell>
      <TableCell className="text-muted-foreground px-3 py-2 tabular-nums" title={cifs.join(", ")}>
        {cifs.length > 1 ? `${cifs[0]} +${cifs.length - 1}` : (cifs[0] ?? "-")}
      </TableCell>
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
  );
});

const CORTES = [
  { key: "top20" as const, label: "Top 20" },
  { key: "cuota" as const, label: "Cuota" },
  { key: "ticket" as const, label: "Ticket vs cliente" },
  { key: "ccaa" as const, label: "Actividad CCAA" },
  { key: "treemap" as const, label: "Treemap" },
  { key: "top5" as const, label: "Top 5 métricas" },
  { key: "estac" as const, label: "Estacionalidad" },
  { key: "bajas" as const, label: "Bajas" },
  { key: "radar" as const, label: "Comparador" },
] as const;

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
    mutationFn: async (e: { empresaIds: number[]; watched: boolean }) =>
      Promise.all(
        e.empresaIds.map((id) =>
          e.watched
            ? apiMutate("DELETE", `/api/v1/competitive/watchlist/${id}`)
            : apiMutate("POST", "/api/v1/competitive/watchlist", {
                empresa_id: id,
                frequency: "daily",
              }),
        ),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["watchlist-empresas"] }),
  });

  const [search, setSearch] = useState("");
  const [corte, setCorte] = useState<(typeof CORTES)[number]["key"]>("top20");
  const { ccaas, setCcaas } = useFilters();
  const activeCcaa = useMemo(() => new Set(ccaas), [ccaas]);
  const toggleCcaa = useCallback((ccaa: string) => setCcaas(toggleValue(ccaa, ccaas)), [ccaas, setCcaas]);
  const { sortKey, sortDir, toggleSort } = useSortToggle<SortKey>("count");
  const [selectedCompanies, setSelectedCompanies] = useState<string[]>([]);
  const [drillDownCompany, setDrillDownCompany] = useState<Competitor | null>(null);
  // Grupo de identidades del maestro que representan al mismo competidor
  // analítico (mismo nombre/NIF conectado, aún sin fusionar). El dossier
  // siempre agrega todas — el usuario nunca elige cuál abrir.
  const drillDownGroupIds = useMemo(() => drillDownIds(drillDownCompany), [drillDownCompany]);
  const drillDownCompanyId = drillDownGroupIds[0];
  const drillDownParams = useMemo(
    () => drillDownExtraParams(drillDownGroupIds),
    [drillDownGroupIds],
  );
  const { data: drillDownProfile, isLoading: isLoadingDrillDownProfile } = useFilteredQuery<CompanyProfileData>(
    ["competitive-company-profile", String(drillDownCompanyId ?? "none"), drillDownGroupIds.join(",")],
    `/api/v1/competitive/empresas/${drillDownCompanyId ?? 0}/perfil`,
    {
      enabled: drillDownCompanyId != null,
      staleTime: 5 * 60 * 1000,
    },
    drillDownParams,
  );
  const { data: drillDownAwards, isLoading: isLoadingDrillDownAwards } = useFilteredQuery<CompanyAwardsData>(
    [
      "competitive-company-awards-preview",
      String(drillDownCompanyId ?? "none"),
      drillDownGroupIds.join(","),
    ],
    `/api/v1/competitive/empresas/${drillDownCompanyId ?? 0}/adjudicaciones`,
    {
      enabled: drillDownCompanyId != null,
      staleTime: 5 * 60 * 1000,
    },
    { limit: "5", offset: "0", sort: "fecha_desc", ...drillDownParams },
  );


  const onToggleCompare = useCallback(
    (nombre: string) => setSelectedCompanies((prev) => toggleCompareSelection(prev, nombre)),
    [],
  );

  // Todas las series de la pantalla (búsqueda, orden, tarta, barras, dispersión,
  // mapa de calor, radar, treemap, posicionamiento, estacionalidad y ranking de
  // bajas) viven en `_hooks/use-competidores-view.ts` como funciones puras.
  const {
    filteredSorted,
    pieData,
    barData,
    scatterData,
    scatterTop5,
    heatmapData,
    radarData,
    treemapData,
    positioningData,
    estacionalidadData,
    bajasSorted,
  } = useCompetidoresView({
    competitors: data?.competitors,
    scatterData: data?.scatter_data,
    heatmapCcaa: data?.heatmap_ccaa,
    estacionalidad: data?.estacionalidad,
    importeTotal: data?.importe_total,
    bajas: bajasData?.items,
    search,
    sortKey,
    sortDir,
    selectedCompanies,
  });

  if (error) {
    return (
      <div className="border-destructive/50 bg-destructive/10 rounded-lg border p-6 text-center" role="alert">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  // Mismo trato que en `/resumen`: con cobertura insuficiente no se pinta un
  // número atenuado, se dice qué falta. Un porcentaje en gris sigue siendo un
  // porcentaje en la cabeza de quien lo lee.
  const ofertaUnica = celdaSaludPorPct(
    data?.pct_oferta_unica,
    data?.cobertura_ofertas_pct,
    "licitaciones con un solo ofertante",
  );

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
    { key: "pct_top_organo", label: "% Top Órgano" },
    { key: "ultima", label: "Última Adj." },
  ];

  return (
    <div className="flex min-h-0 gap-4">
      <div className="min-w-0 flex-1 space-y-4">
        {/* El buscador filtra la tabla **y los nueve cortes**; antes había que
            descubrirlo, ahora se anuncia. Exportar arrastra el ámbito activo. */}
        <div className="flex flex-wrap items-center gap-2.5">
          <SearchAutocomplete
            className="w-full sm:w-72"
            placeholder="Buscar empresa…"
            value={search}
            onChange={setSearch}
            suggestions={data?.competitors?.map((c) => c.nombre) ?? []}
            leftIcon={<Search className="h-4 w-4" />}
            inputClassName="h-8 pl-9 text-xs"
          />
          {search.trim() && (
            <span className="rounded border border-primary/30 bg-primary/10 px-1.5 py-1 text-[10.5px] font-medium text-primary">
              filtra la tabla y los 9 cortes
            </span>
          )}
          <div className="flex-1" />
          <ExportPopover
            extraParams={{ section: "competitors" }}
            className="[&>button]:h-8 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs"
          />
        </div>

        {/* Marcador del espacio: los cuatro KPIs del mercado competitivo. */}
      {/* KPI Row */}
      <Stagger className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border/60 bg-border/60 lg:grid-cols-4 [&_[data-slot=card]]:rounded-none [&_[data-slot=card]]:border-0 [&_[data-slot=card]]:bg-card">
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
            title="HHI Concentración"
            value={isLoading ? undefined : formatNumber(data?.hhi)}
            subtitle={
              data?.hhi != null
                ? data.hhi < 1500
                  ? "Mercado competitivo"
                  : data.hhi < 2500
                    ? "Concentración moderada"
                    : "Mercado concentrado"
                : undefined
            }
            icon={Target}
            loading={isLoading}
          />
        </Stagger.Item>
        <Stagger.Item>
          <KpiCard
            title="% Oferta Única"
            value={isLoading ? undefined : ofertaUnica.value}
            subtitle={isLoading ? undefined : ofertaUnica.hint}
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

        {/* La tabla gobierna los nueve cortes, así que va primero. Antes había
            que bajar 2.400px de gráficos para llegar a la superficie de trabajo
            que los filtra. */}
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
                  {filteredSorted.map((c, idx) => {
                    const identityCount = c.empresa_ids?.length ?? 0;
                    const rowKey =
                      identityCount > 0
                        ? `ids:${c.empresa_ids!.join("-")}`
                        : c.nifs?.length
                          ? `nifs:${c.nifs.join("-")}`
                          : `nombre:${c.nombre}:${idx}`;

                    return (
                      <CompetitorRow
                        key={rowKey}
                        competitor={c}
                        selected={selectedCompanies.includes(c.nombre)}
                        onToggleCompare={onToggleCompare}
                        onDrillDown={setDrillDownCompany}
                      />
                    );
                  })}
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

      {selectedCompanies.length > 0 && selectedCompanies.length < 2 && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-300">
          Selecciona 1 empresa mas en la tabla para comparar con radar. ({selectedCompanies.length}/2 seleccionadas)
        </div>
      )}

        {/* Los nueve gráficos, como cortes con pestañas de la misma tabla. */}
        <Panel>
          <PanelTabs
            label="Cortes del análisis de competencia"
            value={corte}
            onChange={setCorte}
            tabs={[...CORTES]}
          />
          <div className="pt-3.5">
        {corte === "top20" && (
          <>
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
          </>
        )}
        {corte === "cuota" && (
          <>
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
          </>
        )}
        {corte === "ticket" && (
          <>
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
          </>
        )}
        {corte === "ccaa" && (
          <>
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
                    <Tooltip key={ccaa}>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          onClick={() => toggleCcaa(ccaa)}
                          aria-pressed={activeCcaa.has(ccaa)}
                          aria-label={`Filtrar por ${ccaa}`}
                          className={`hover:bg-muted cursor-pointer truncate rounded-sm p-1 text-center font-medium transition-colors ${activeCcaa.has(ccaa) ? "bg-primary/15 text-primary" : "text-muted-foreground"}`}
                        >
                          {truncate(ccaa, 10)}
                        </button>
                      </TooltipTrigger>
                      <TooltipContent>{`Filtrar por ${ccaa}`}</TooltipContent>
                    </Tooltip>
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
          </>
        )}
        {corte === "treemap" && (
          <>
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
          </>
        )}
        {corte === "top5" && (
          <>
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
          </>
        )}
        {corte === "estac" && (
          <>
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
          </>
        )}
        {corte === "bajas" && (
          <>
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
                      // fdi-allow:nulo-a-cero — ancho de la barra: sin dato no se dibuja.
                      style={{ width: `${((b.baja_media_pct ?? 0) / bajasSorted.maxBaja) * 100}%` }}
                    />
                  </div>
                  <span className="w-14 text-right text-xs tabular-nums">
                    {valorOEmpty(b.baja_media_pct, formatPercent)}
                  </span>
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
          </>
        )}
        {corte === "radar" && (
          <>
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
          </>
        )}
          </div>
        </Panel>
      </div>

      {/* El dossier deja de ser un Sheet modal que tapaba la tabla de la que
          venías: vive en el mismo plano, a la derecha, y la tabla sigue ahí
          para saltar a la siguiente empresa sin cerrar nada. */}
      {drillDownCompany && (
        <aside
          aria-label="Dossier de empresa"
          className="hidden w-[420px] flex-none flex-col overflow-hidden rounded-xl border border-border/60 bg-card/40 xl:flex"
        >
          <div className="flex h-9 flex-none items-center gap-2 border-b border-border/60 px-3">
            <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Dossier
            </span>
            <div className="flex-1" />
            <button
              type="button"
              aria-label="Cerrar dossier"
              onClick={() => startTransition(() => setDrillDownCompany(null))}
              className="tf-pressable grid h-6 w-6 place-items-center rounded-md border border-border/70 text-muted-foreground transition-colors hover:text-foreground"
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
          {drillDownCompanyId != null ? (
            <CompanyQuickView
              empresaId={drillDownCompanyId}
              groupIds={drillDownGroupIds}
              company={{ ...drillDownCompany, nif: drillDownCompany.nif ?? undefined }}
              profile={drillDownProfile}
              recentAwards={drillDownAwards}
              isLoadingProfile={isLoadingDrillDownProfile}
              isLoadingAwards={isLoadingDrillDownAwards}
              watched={drillDownGroupIds.some((id) => watchedIds.has(id))}
              watchPending={toggleWatch.isPending}
              onToggleWatch={() =>
                toggleWatch.mutate({
                  empresaIds: drillDownGroupIds,
                  watched: drillDownGroupIds.some((id) => watchedIds.has(id)),
                })
              }
            />
          ) : null}
          </div>
        </aside>
      )}
    </div>
  );
}
