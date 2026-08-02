"use client";
import { EmptyState } from "@/components/ui/empty-state";

import { useMemo, useState } from "react";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { ExportPopover } from "@/components/export-popover";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatCurrency, formatNumber, truncate } from "@/lib/utils";
import { ChartErrorBoundary } from "@/components/charts/chart-error-boundary";
import { CHART_SERIES } from "@/lib/chart-colors";
import { Handshake, Users, TrendingUp, Building2, Search } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Line,
  Legend,
  ComposedChart,
} from "recharts";

interface UTEsKpis {
  total_ute: number;
  importe_ute: number;
  ticket_medio_ute: number;
  ticket_medio_individual: number;
  empresas_distintas: number;
}

interface TopMiembro {
  nombre: string;
  count: number;
  importe: number;
}

interface EvolucionEntry {
  periodo: string;
  count: number;
  importe: number;
}

interface TablaComparativa {
  ute: { contratos: number; importe_medio: number; importe_total: number };
  individual: { contratos: number; importe_medio: number; importe_total: number };
}

interface SocioPar {
  empresa_a: string;
  empresa_b: string;
  contratos: number;
  importe: number;
}

interface UTEsData {
  kpis: UTEsKpis;
  top_miembros: TopMiembro[];
  socios_frecuentes?: SocioPar[];
  evolucion: EvolucionEntry[];
  tabla_comparativa: TablaComparativa;
}

export default function UtesPage() {
  const { data, isLoading, error } = useFilteredQuery<UTEsData>(
    ["analytics", "utes"],
    "/api/v1/analytics/utes",
    { staleTime: 5 * 60 * 1000 },
  );

  const [memberSearch, setMemberSearch] = useState("");

  const kpis = data?.kpis;
  const comparativa = data?.tabla_comparativa;

  const comparativaRows = useMemo(() => {
    if (!comparativa) return [];
    return [
      { metrica: "Contratos", ute: formatNumber(comparativa.ute.contratos), individual: formatNumber(comparativa.individual.contratos) },
      { metrica: "Importe medio", ute: formatCurrency(comparativa.ute.importe_medio), individual: formatCurrency(comparativa.individual.importe_medio) },
      { metrica: "Importe total", ute: formatCurrency(comparativa.ute.importe_total), individual: formatCurrency(comparativa.individual.importe_total) },
    ];
  }, [comparativa]);

  // Filter members by search
  const filteredMiembros = useMemo(() => {
    if (!data?.top_miembros) return [];
    if (!memberSearch) return data.top_miembros;
    const q = memberSearch.toLowerCase();
    return data.top_miembros.filter((m) => m.nombre.toLowerCase().includes(q));
  }, [data, memberSearch]);

  // Distribution of member participation counts
  const memberDistribution = useMemo(() => {
    if (!data?.top_miembros?.length) return [];
    const bins: Record<string, number> = {};
    for (const m of data.top_miembros) {
      const bucket = m.count <= 1 ? "1" : m.count <= 3 ? "2-3" : m.count <= 5 ? "4-5" : m.count <= 10 ? "6-10" : "11+";
      bins[bucket] = (bins[bucket] ?? 0) + 1;
    }
    const order = ["1", "2-3", "4-5", "6-10", "11+"];
    return order.filter((k) => bins[k]).map((k) => ({ rango: k + " UTEs", miembros: bins[k] }));
  }, [data]);

  // Top members by importe (if available)
  const topMiembrosByImporte = useMemo(() => {
    if (!data?.top_miembros?.length) return [];
    return [...data.top_miembros]
      .filter((m) => m.importe > 0)
      .sort((a, b) => b.importe - a.importe)
      .slice(0, 15);
  }, [data]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* El nombre del corte lo pone la cabecera del espacio; aquí queda la
          acción, que es lo único que no puede vivir allí. */}
      <div className="flex items-center">
        <div className="flex-1" />
        <ExportPopover
          extraParams={{ section: "utes" }}
          className="[&>button]:h-8 [&>button]:px-2.5 [&>button]:py-0 [&>button]:text-xs"
        />
      </div>

      {/* KPI Row — 5 cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <KpiCard
          title="Total UTEs"
          value={isLoading ? undefined : formatNumber(kpis?.total_ute)}
          icon={Handshake}
          loading={isLoading}
        />
        <KpiCard
          title="Importe UTEs"
          value={isLoading ? undefined : formatCurrency(kpis?.importe_ute)}
          icon={TrendingUp}
          loading={isLoading}
        />
        <KpiCard
          title="Ticket Medio UTE"
          value={isLoading ? undefined : formatCurrency(kpis?.ticket_medio_ute)}
          loading={isLoading}
        />
        <KpiCard
          title="Ticket Medio Individual"
          value={isLoading ? undefined : formatCurrency(kpis?.ticket_medio_individual)}
          loading={isLoading}
        />
        <KpiCard
          title="Empresas Distintas"
          value={isLoading ? undefined : formatNumber(kpis?.empresas_distintas)}
          icon={Users}
          loading={isLoading}
        />
      </div>

      {/* Charts Row: Top miembros + Evolucion */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Top miembros — horizontal bar */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top Miembros de UTEs</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : data?.top_miembros && data.top_miembros.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(300, data.top_miembros.length * 32)}>
                <BarChart accessibilityLayer
                  data={data.top_miembros}
                  layout="vertical"
                  margin={{ left: 180 }}
                >
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis type="number" tick={{ fontSize: 12 }} />
                  <YAxis
                    dataKey="nombre"
                    type="category"
                    tick={{ fontSize: 11 }}
                    width={170}
                    tickFormatter={(v: string) => truncate(v, 30)}
                  />
                  <Tooltip formatter={(v) => formatNumber(v as number)} />
                  <Bar dataKey="count" fill="hsl(280, 65%, 60%)" radius={[0, 4, 4, 0]} name="Participaciones" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        {/* Evolucion temporal — composed bar + line */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Evolucion Temporal de UTEs</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : data?.evolucion && data.evolucion.length > 0 ? (
              <ResponsiveContainer width="100%" height={400}>
                <ComposedChart accessibilityLayer data={data.evolucion} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis dataKey="periodo" tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v: number) => formatCurrency(v)}
                  />
                  <Tooltip
                    formatter={(v, name) =>
                      name === "Importe" ? formatCurrency(Number(v ?? 0)) : formatNumber(Number(v ?? 0))
                    }
                  />
                  <Legend />
                  <Bar yAxisId="left" dataKey="count" fill="hsl(221, 83%, 53%)" radius={[4, 4, 0, 0]} name="Contratos" />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="importe"
                    stroke="hsl(30, 80%, 55%)"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    name="Importe"
                  />
                </ComposedChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Socios frecuentes — quién se asocia con quién (co-licitación real) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Handshake className="h-4 w-4" />
            Socios Frecuentes (quién se asocia con quién)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[200px] w-full" />
          ) : (data?.socios_frecuentes?.length ?? 0) > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="text-left text-muted-foreground">
                    <TableHead>Empresa</TableHead>
                    <TableHead>Socio</TableHead>
                    <TableHead>UTEs juntas</TableHead>
                    <TableHead>Importe conjunto</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data!.socios_frecuentes!.map((s, idx) => (
                    <TableRow key={idx}>
                      <TableCell className="font-medium">{truncate(s.empresa_a, 35)}</TableCell>
                      <TableCell className="font-medium">{truncate(s.empresa_b, 35)}</TableCell>
                      <TableCell className="tabular-nums">{formatNumber(s.contratos)}</TableCell>
                      <TableCell className="tabular-nums">{formatCurrency(s.importe)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                Pares de empresas que han formado UTE conjunta (co-licitacion real,
                no co-ocurrencia geografica).
              </p>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">
              Sin pares de co-licitacion detectados
            </p>
          )}
        </CardContent>
      </Card>

      {/* Charts Row 2: Distribution + Top by importe */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Member participation distribution */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Distribución de Participaciones</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[300px] w-full" />
            ) : memberDistribution.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart accessibilityLayer data={memberDistribution} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis dataKey="rango" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v) => [formatNumber(v as number), "Empresas"]} />
                  <Bar dataKey="miembros" fill={CHART_SERIES[0]} radius={[4, 4, 0, 0]} name="Empresas" />
                </BarChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>

        {/* Top members by importe */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top 15 Miembros por Importe</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : topMiembrosByImporte.length > 0 ? (
              <ChartErrorBoundary>
              <ResponsiveContainer width="100%" height={Math.max(300, topMiembrosByImporte.length * 28)}>
                <BarChart accessibilityLayer
                  data={topMiembrosByImporte}
                  layout="vertical"
                  margin={{ left: 180 }}
                >
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={(v: number) => formatCurrency(v)} />
                  <YAxis
                    dataKey="nombre"
                    type="category"
                    tick={{ fontSize: 11 }}
                    width={170}
                    tickFormatter={(v: string) => truncate(v, 30)}
                  />
                  <Tooltip formatter={(v) => [formatCurrency(v as number), "Importe"]} />
                  <Bar dataKey="importe" fill={CHART_SERIES[1]} radius={[0, 4, 4, 0]} name="Importe" />
                </BarChart>
              </ResponsiveContainer>
              </ChartErrorBoundary>
            ) : (
              <EmptyState />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Tabla comparativa UTE vs Individual */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Building2 className="h-4 w-4" />
            Comparativa UTE vs Individual
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[120px] w-full" />
          ) : comparativaRows.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="text-left text-muted-foreground">
                    <TableHead>Metrica</TableHead>
                    <TableHead>
                      <span className="inline-flex items-center gap-1">
                        <Badge variant="default" className="text-xs">UTE</Badge>
                      </span>
                    </TableHead>
                    <TableHead>
                      <span className="inline-flex items-center gap-1">
                        <Badge variant="secondary" className="text-xs">Individual</Badge>
                      </span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {comparativaRows.map((row) => (
                    <TableRow key={row.metrica}>
                      <TableCell className="font-medium">{row.metrica}</TableCell>
                      <TableCell className="tabular-nums">{row.ute}</TableCell>
                      <TableCell className="tabular-nums">{row.individual}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">Sin datos comparativos disponibles</p>
          )}
        </CardContent>
      </Card>

      {/* Full UTEs Table with search */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Handshake className="h-4 w-4" />
              Todas las UTEs
            </CardTitle>
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Buscar miembro..."
                value={memberSearch}
                onChange={(e) => setMemberSearch(e.target.value)}
                className="pl-8"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : filteredMiembros.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="text-left text-muted-foreground">
                    <TableHead>#</TableHead>
                    <TableHead>Nombre</TableHead>
                    <TableHead>Participaciones</TableHead>
                    <TableHead>Importe</TableHead>
                    <TableHead>Importe Medio</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredMiembros.map((m, idx) => (
                    <TableRow key={idx}>
                      <TableCell className="text-muted-foreground tabular-nums">{idx + 1}</TableCell>
                      <TableCell className="font-medium">
                        <div className="flex items-center gap-2">
                          {m.nombre}
                          <Badge variant="outline" className="text-xs">UTE</Badge>
                        </div>
                      </TableCell>
                      <TableCell className="tabular-nums">{formatNumber(m.count)}</TableCell>
                      <TableCell className="tabular-nums">{formatCurrency(m.importe)}</TableCell>
                      <TableCell className="tabular-nums">{m.count > 0 ? formatCurrency(m.importe / m.count) : "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                Mostrando {filteredMiembros.length} de {data?.top_miembros?.length ?? 0} miembros
              </p>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">
              {memberSearch ? "No se encontraron miembros" : "Sin datos de UTEs disponibles"}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
