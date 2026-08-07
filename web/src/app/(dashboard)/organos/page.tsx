"use client";
import { EmptyState } from "@/components/ui/empty-state";

import { startTransition, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { useDebounce } from "@/hooks/use-debounce";
import { KpiCard, KpiStrip } from "@/components/charts/kpi-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { SearchAutocomplete } from "@/components/ui/search-autocomplete";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ExportPopover } from "@/components/export-popover";
import { foldText, formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/utils";
import { CHART_SERIES } from "@/lib/chart-colors";
import {
  Building2,
  X,
  Hash,
  Trophy,
  BarChart3,
  Search,
  Clock,
  Users,
  TrendingUp,
} from "lucide-react";
const OrganosRankingChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosRankingChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const OrganosTreemapChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosTreemapChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const OrganosAdjudicatariosChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosAdjudicatariosChart })), { ssr: false, loading: () => <Skeleton className="h-[280px] w-full rounded-md" /> });
const OrganosEstacionalidadChart = dynamic(() => import("@/components/charts/organos-charts").then(m => ({ default: m.OrganosEstacionalidadChart })), { ssr: false, loading: () => <Skeleton className="h-[200px] w-full rounded-md" /> });

const TIPO_CONTRATO_LABEL: Record<string, string> = { "1": "Servicios", "2": "Suministros", "3": "Obras" };

interface OrganoItem {
  organo_contratacion: string;
  count: number;
  importe: number;
  pct: number;
  ccaa?: string;
}

interface TreemapBreakdownItem {
  organo: string;
  tipo_contrato: string;
  importe: number;
}

interface OrganosResponse {
  organos: OrganoItem[];
  total_organos: number;
  importe_total?: number;
  concentracion_top10?: number;
  treemap_breakdown?: TreemapBreakdownItem[];
}

interface OrganoKpis {
  total_licitaciones: number;
  importe_total: number;
  importe_medio: number;
  pct_adjudicado: number;
  lead_time_medio: number | null;
  top_adjudicatario: string | null;
  top_adj_importe: number;
}

interface TopScoredItem {
  id_externo: string;
  titulo: string | null;
  importe: number | null;
  score: number;
  ccaa?: string | null;
  estado?: string | null;
  estado_desc?: string | null;
  banda?: string | null;
  empresa?: string | null;
  baja_pct?: number | null;
  fecha_adjudicacion?: string | null;
  modulos_str?: string | null;
  url?: string | null;
  tipo_proyecto?: string | null;
  tipo_contrato_desc?: string | null;
  cpv_desc?: string | null;
}

interface OrganoDetailResponse {
  kpis: OrganoKpis;
  top_adjudicatarios: { nombre: string; count: number; importe: number }[];
  estacionalidad: { mes_numero: number; count: number }[];
  top_scored: TopScoredItem[];
}

export default function OrganosPage() {
  const searchParams = useSearchParams();
  // Deep-link externo: `?q=<órgano>` siembra el filtro.
  const [filter, setFilter] = useState(() => searchParams?.get("q") ?? "");
  const [selectedOrgano, setSelectedOrgano] = useState<string | null>(null);

  // Búsqueda server-side (accent-insensitive): sin q el API devuelve solo el
  // top-50 por actividad, así que un órgano fuera de ese ranking jamás
  // aparecería filtrando solo en cliente.
  const debouncedFilter = useDebounce(filter, 300);
  const { data, isLoading, error } = useFilteredQuery<OrganosResponse>(
    ["analytics", "organos", debouncedFilter],
    "/api/v1/analytics/organos",
    { staleTime: 5 * 60 * 1000 },
    debouncedFilter ? { q: debouncedFilter } : undefined,
  );

  const { data: detailData, isLoading: detailLoading } =
    useQuery<OrganoDetailResponse>({
      queryKey: ["analytics", "organos", selectedOrgano],
      queryFn: async () => {
        const res = await fetch(
          `/api/v1/analytics/organos/${encodeURIComponent(selectedOrgano!)}`,
          { credentials: "include" },
        );
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        return res.json();
      },
      enabled: !!selectedOrgano,
      staleTime: 5 * 60 * 1000,
    });

  const items = useMemo(() => data?.organos ?? [], [data]);

  // Totales reales del backend (sobre TODO el dataset), no la suma del top-50
  // que devuelve `items`: antes "Concentración Top 10" se inflaba (denominador =
  // top-50) e "Importe Total" se subestimaba (ignoraba órganos fuera del top-50).
  const top10Concentration = data?.concentracion_top10 ?? 0;
  const totalImporte = data?.importe_total ?? 0;

  const topOrgano = items.length > 0 ? items[0].organo_contratacion : "-";

  const filteredItems = useMemo(() => {
    if (!filter) return items;
    const q = foldText(filter);
    return items.filter(
      (i) =>
        foldText(i.organo_contratacion).includes(q) ||
        (i.ccaa && foldText(i.ccaa).includes(q)),
    );
  }, [items, filter]);

  const maxCount = useMemo(
    () => (filteredItems.length > 0 ? Math.max(...filteredItems.map((i) => i.count)) : 1),
    [filteredItems],
  );

  const top20 = useMemo(() => filteredItems.slice(0, 20), [filteredItems]);

  const top15ByImporte = useMemo(
    () => [...filteredItems].sort((a, b) => b.importe - a.importe).slice(0, 15),
    [filteredItems],
  );

  // Hierarchical treemap: organo → tipo_contrato if backend provides breakdown
  const treemapData = useMemo(() => {
    const breakdown = data?.treemap_breakdown;
    if (breakdown && breakdown.length > 0) {
      // Filter by local search if active
      const relevant = filter
        ? breakdown.filter((b) => foldText(b.organo).includes(foldText(filter)))
        : breakdown;
      const map = new Map<string, { name: string; children: { name: string; size: number }[] }>();
      for (const item of relevant) {
        const key = item.organo;
        if (!map.has(key)) {
          map.set(key, { name: key.slice(0, 40), children: [] });
        }
        const label = TIPO_CONTRATO_LABEL[item.tipo_contrato] ?? item.tipo_contrato ?? "Otro";
        map.get(key)!.children.push({ name: label, size: item.importe });
      }
      return Array.from(map.values());
    }
    // Fallback: flat treemap
    return filteredItems
      .filter((i) => i.importe > 0)
      .slice(0, 30)
      .map((i) => ({ name: i.organo_contratacion, size: i.importe }));
  }, [data, filteredItems, filter]);

  function handleOrganoClick(organo: string) {
    setSelectedOrgano(organo);
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 gap-4">
      <div className="min-w-0 flex-1 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="sr-only">Órganos</h1>
          <p className="text-muted-foreground">
            Ranking de órganos de contratación.
          </p>
        </div>
        <ExportPopover
          endpoint="/api/v1/exports/download"
          extraParams={{ section: "organos" }}
        />
      </div>

      {/* Search filter */}
      <SearchAutocomplete
        className="max-w-sm"
        placeholder="Buscar órgano o CCAA..."
        value={filter}
        onChange={setFilter}
        suggestions={[
          ...(data?.organos?.map((i) => i.organo_contratacion) ?? []),
          ...[...new Set(data?.organos?.map((i) => i.ccaa).filter((c): c is string => c != null) ?? [])],
        ]}
        leftIcon={<Search className="h-4 w-4" />}
        inputClassName="pl-9"
      />

      {/* KPI Row */}
      <KpiStrip columns={4}>
        <KpiCard
          title="Total Órganos"
          value={isLoading ? undefined : formatNumber(data?.total_organos ?? items.length)}
          icon={Building2}
          loading={isLoading}
        />
        <KpiCard
          title="Concentración Top 10"
          value={isLoading ? undefined : formatPercent(top10Concentration)}
          subtitle="del total de licitaciones"
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Importe Total"
          value={isLoading ? undefined : formatCurrency(totalImporte)}
          icon={TrendingUp}
          loading={isLoading}
        />
        <KpiCard
          title="Top Órgano"
          value={
            isLoading
              ? undefined
              : topOrgano.length > 40
                ? topOrgano.slice(0, 40) + "..."
                : topOrgano
          }
          icon={Trophy}
          loading={isLoading}
        />
      </KpiStrip>

      {/* Top charts: by count + by importe */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="h-4 w-4" />
              Top 20 Órganos por Cantidad
              {filter && (
                <Badge variant="secondary" className="ml-2 text-xs">filtrado</Badge>
              )}
            </CardTitle>
            <CardDescription>clic en una barra abre el órgano</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[500px] w-full" />
            ) : top20.length > 0 ? (
              <OrganosRankingChart
                data={top20}
                dataKey="count"
                fill={CHART_SERIES[0]}
                tooltipLabel="Licitaciones"
                formatValue={formatNumber}
                onBarClick={handleOrganoClick}
              />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="h-4 w-4" />
              Top 15 Órganos por Importe
              {filter && (
                <Badge variant="secondary" className="ml-2 text-xs">filtrado</Badge>
              )}
            </CardTitle>
            <CardDescription>clic en una barra abre el órgano</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[500px] w-full" />
            ) : top15ByImporte.length > 0 ? (
              <OrganosRankingChart
                data={top15ByImporte}
                dataKey="importe"
                // Mismo color que el ranking por cantidad: son el mismo
                // conjunto (órganos) medido de otra forma. El color de serie
                // se reserva para distinguir series, no paneles.
                fill={CHART_SERIES[0]}
                tooltipLabel="Importe"
                formatValue={formatCurrency}
                onBarClick={handleOrganoClick}
              />
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Treemap: organo → tipo_contrato → importe */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Treemap: Órganos → Tipo de Proyecto → Importe
            {filter && (
              <Badge variant="secondary" className="ml-2 text-xs">filtrado</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : treemapData.length > 0 ? (
            <OrganosTreemapChart data={treemapData} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* Ranking table with progress bars */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Listado Completo</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow className="border-b text-left">
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground">
                      Órgano
                    </TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground w-40">
                      Licitaciones
                    </TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground text-right">
                      Importe
                    </TableHead>
                    <TableHead className="pb-2 pr-4 font-medium text-muted-foreground text-right">
                      %
                    </TableHead>
                    <TableHead className="pb-2 font-medium text-muted-foreground">
                      CCAA
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredItems.map((item, idx) => (
                    <TableRow
                      key={idx}
                      className="border-b border-border/50 hover:bg-muted/50 cursor-pointer"
                      tabIndex={0}
                      role="row"
                      onClick={() => handleOrganoClick(item.organo_contratacion)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ")
                          handleOrganoClick(item.organo_contratacion);
                      }}
                    >
                      <TableCell
                        className="py-2 pr-4 max-w-xs truncate"
                        title={item.organo_contratacion}
                      >
                        {item.organo_contratacion}
                      </TableCell>
                      <TableCell className="py-2 pr-4 w-40">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
                            <div
                              className="h-full bg-primary rounded-full transition-[width]"
                              style={{ width: `${(item.count / maxCount) * 100}%` }}
                            />
                          </div>
                          <span className="tabular-nums text-xs w-8 text-right shrink-0">
                            {formatNumber(item.count)}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatCurrency(item.importe)}
                      </TableCell>
                      <TableCell className="py-2 pr-4 text-right tabular-nums">
                        {formatPercent(item.pct)}
                      </TableCell>
                      <TableCell className="py-2">
                        {item.ccaa ? (
                          <Badge variant="secondary">{item.ccaa}</Badge>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                  {filteredItems.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={5}
                        className="py-8 text-center text-muted-foreground"
                      >
                        Sin resultados
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      </div>

      {/* El drill-down era un Sheet modal que tapaba el ranking del que venías,
          justo cuando lo que quieres es comparar dos órganos. Ahora vive en el
          mismo plano y el ranking sigue ahí para saltar al siguiente. */}
      {selectedOrgano && (
        <aside
          aria-label={`Detalle de ${selectedOrgano}`}
          className="hidden w-[420px] flex-none flex-col overflow-hidden rounded-xl border border-border/60 bg-card/40 xl:flex"
        >
          <div className="flex flex-none items-start gap-2 border-b border-border/60 px-3.5 py-2.5">
            <h2 className="min-w-0 flex-1 text-[13px] font-semibold leading-tight">
              {selectedOrgano}
            </h2>
            <button
              type="button"
              aria-label="Cerrar detalle del órgano"
              onClick={() => startTransition(() => setSelectedOrgano(null))}
              className="tf-pressable grid h-6 w-6 flex-none place-items-center rounded-md border border-border/70 text-muted-foreground transition-colors hover:text-foreground"
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-3.5 pb-4">

          {detailLoading ? (
            <div className="mt-6 space-y-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : detailData ? (
            <div className="mt-6 space-y-6">
              {/* Detail KPIs */}
              <div className="grid grid-cols-2 gap-3">
                <KpiCard
                  title="Licitaciones"
                  value={formatNumber(detailData.kpis.total_licitaciones)}
                  icon={Hash}
                />
                <KpiCard
                  title="Importe Total"
                  value={formatCurrency(detailData.kpis.importe_total)}
                  subtitle={detailData.kpis.importe_medio > 0
                    ? `medio ${formatCurrency(detailData.kpis.importe_medio)}`
                    : undefined}
                  icon={TrendingUp}
                />
                <KpiCard
                  title="% Adjudicado"
                  value={formatPercent(detailData.kpis.pct_adjudicado)}
                  subtitle="del total del órgano"
                  icon={Trophy}
                />
                <KpiCard
                  title="Lead Time Mediano"
                  value={
                    detailData.kpis.lead_time_medio != null
                      ? `${Math.round(detailData.kpis.lead_time_medio)} días`
                      : "— d"
                  }
                  subtitle="pub → adj"
                  icon={Clock}
                />
              </div>

              {/* Top adjudicatario caption */}
              {detailData.kpis.top_adjudicatario && (
                <p className="text-xs text-muted-foreground">
                  🏆 <strong>Top adjudicatario:</strong> {detailData.kpis.top_adjudicatario}
                  {detailData.kpis.top_adj_importe > 0 && (
                    <> ({formatCurrency(detailData.kpis.top_adj_importe)})</>
                  )}
                </p>
              )}

              {/* Top adjudicatarios chart */}
              {detailData.top_adjudicatarios?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <Users className="h-4 w-4" />
                      Top 10 Adjudicatarios
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <OrganosAdjudicatariosChart data={detailData.top_adjudicatarios} />
                  </CardContent>
                </Card>
              )}

              {/* Estacionalidad */}
              {detailData.estacionalidad?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Estacionalidad mensual</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <OrganosEstacionalidadChart data={detailData.estacionalidad} />
                  </CardContent>
                </Card>
              )}

              {/* Top 30 por score — rich cards */}
              {detailData.top_scored?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">
                      Top {detailData.top_scored.length} por Score
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {detailData.top_scored.slice(0, 30).map((s, i) => (
                        <div key={i} className="rounded-lg border p-3 space-y-1">
                          <div className="flex items-start justify-between gap-2">
                            {s.url ? (
                              <a
                                href={s.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-sm font-medium leading-tight line-clamp-2 hover:underline text-primary"
                              >
                                {s.titulo ?? s.id_externo}
                              </a>
                            ) : (
                              <p className="text-sm font-medium leading-tight line-clamp-2">
                                {s.titulo ?? s.id_externo}
                              </p>
                            )}
                            <Badge
                              variant={
                                s.score >= 80
                                  ? "default"
                                  : s.score >= 60
                                    ? "secondary"
                                    : "outline"
                              }
                              className="shrink-0"
                            >
                              {s.banda ? `${s.banda} · ${s.score}` : s.score}
                            </Badge>
                          </div>
                          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                            {s.importe != null && (
                              <span className="font-medium text-foreground">
                                {formatCurrency(s.importe)}
                              </span>
                            )}
                            {(s.estado_desc || s.estado) && (
                              <span>{s.estado_desc ?? s.estado}</span>
                            )}
                            {s.tipo_proyecto && <span>{s.tipo_proyecto}</span>}
                            {s.ccaa && <span>{s.ccaa}</span>}
                            {s.empresa && <span>🏢 {s.empresa}</span>}
                            {s.baja_pct != null && (
                              <span>📉 {s.baja_pct.toFixed(1)}% baja</span>
                            )}
                            {s.fecha_adjudicacion && (
                              <span>📅 {formatDate(s.fecha_adjudicacion)}</span>
                            )}
                            {s.modulos_str && (
                              <span className="text-primary">{s.modulos_str}</span>
                            )}
                          </div>
                          {(s.tipo_contrato_desc || s.cpv_desc) && (
                            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground/80">
                              {s.tipo_contrato_desc && (
                                <span>📑 {s.tipo_contrato_desc}</span>
                              )}
                              {s.cpv_desc && (
                                <span className="truncate max-w-full" title={s.cpv_desc}>
                                  🏷️ {s.cpv_desc}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          ) : (
            <p className="mt-6 text-sm text-muted-foreground">
              Sin datos del órgano.
            </p>
          )}
          </div>
        </aside>
      )}
    </div>
  );
}
