"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { formatCurrency, formatNumber, formatPercent, truncate } from "@/lib/utils";
import {
  Trophy,
  Hash,
  Target,
  Info,
  ArrowUpDown,
  Search,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface Competitor {
  nombre: string;
  count: number;
  importe: number;
  cuota: number;
}

interface CompetitorsData {
  total_adjudicaciones: number;
  hhi: number;
  pct_oferta_unica: number;
  top_competidor: string;
  competitors: Competitor[];
}

async function fetchCompetitors(): Promise<CompetitorsData> {
  const res = await fetch("/api/v1/analytics/competitors", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Error al cargar datos de licitadores");
  return res.json();
}

type SortKey = "nombre" | "count" | "importe" | "cuota";
type SortDir = "asc" | "desc";

export default function LicitadoresPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "competitors"],
    queryFn: fetchCompetitors,
    staleTime: 5 * 60 * 1000,
  });

  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("count");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const filteredSorted = useMemo(() => {
    if (!data?.competitors) return [];
    let items = data.competitors;
    if (search) {
      const q = search.toLowerCase();
      items = items.filter((c) => c.nombre.toLowerCase().includes(q));
    }
    return [...items].sort((a, b) => {
      const mul = sortDir === "asc" ? 1 : -1;
      if (sortKey === "nombre") return mul * a.nombre.localeCompare(b.nombre);
      return mul * ((a[sortKey] ?? 0) - (b[sortKey] ?? 0));
    });
  }, [data, search, sortKey, sortDir]);

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
        <p className="text-destructive">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Licitadores</h1>
        <p className="text-muted-foreground">
          Ranking de empresas licitadoras.
        </p>
      </div>

      {/* Info Banner */}
      <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950/30">
        <Info className="mt-0.5 h-5 w-5 shrink-0 text-blue-600 dark:text-blue-400" />
        <div className="text-sm text-blue-800 dark:text-blue-300">
          <p className="font-medium">Datos basados en adjudicaciones</p>
          <p className="mt-1 text-blue-700/80 dark:text-blue-400/80">
            Datos de ofertas (licitaciones presentadas sin adjudicacion) se integraran en futuras versiones.
            Actualmente se muestran las empresas que han resultado adjudicatarias.
          </p>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Total Licitadores"
          value={isLoading ? undefined : formatNumber(data?.competitors.length)}
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Total Adjudicaciones"
          value={isLoading ? undefined : formatNumber(data?.total_adjudicaciones)}
          icon={Trophy}
          loading={isLoading}
        />
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
        <KpiCard
          title="% Oferta Unica"
          value={isLoading ? undefined : formatPercent(data?.pct_oferta_unica)}
          icon={Target}
          loading={isLoading}
        />
      </div>

      {/* Bar Chart: Top licitadores by count */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top 20 Licitadores (por adjudicaciones)</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[500px] w-full" />
          ) : data?.competitors && data.competitors.length > 0 ? (
            <ResponsiveContainer width="100%" height={Math.max(400, Math.min(20, data.competitors.length) * 32)}>
              <BarChart
                data={[...data.competitors].sort((a, b) => b.count - a.count).slice(0, 20)}
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
                <Bar dataKey="count" fill="hsl(160, 60%, 45%)" radius={[0, 4, 4, 0]} name="Adjudicaciones" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-12 text-center text-muted-foreground">Sin datos disponibles</p>
          )}
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle className="text-base">Ranking de Licitadores</CardTitle>
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Buscar licitador..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8"
              />
            </div>
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
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="px-3 py-2 font-medium w-10">#</th>
                    {([["nombre", "Nombre"], ["count", "Adjudicaciones"], ["importe", "Importe"], ["cuota", "Cuota %"]] as const).map(([key, label]) => (
                      <th
                        key={key}
                        className="cursor-pointer select-none px-3 py-2 font-medium hover:text-foreground"
                        onClick={() => toggleSort(key)}
                      >
                        <span className="inline-flex items-center gap-1">
                          {label}
                          <ArrowUpDown className="h-3 w-3" />
                          {sortKey === key && (
                            <Badge variant="secondary" className="ml-1 text-[10px] px-1 py-0">
                              {sortDir === "asc" ? "ASC" : "DESC"}
                            </Badge>
                          )}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredSorted.map((c, idx) => (
                    <tr key={idx} className="border-b last:border-0 hover:bg-muted/50">
                      <td className="px-3 py-2 text-muted-foreground">{idx + 1}</td>
                      <td className="px-3 py-2 font-medium">{c.nombre}</td>
                      <td className="px-3 py-2 tabular-nums">{formatNumber(c.count)}</td>
                      <td className="px-3 py-2 tabular-nums">{formatCurrency(c.importe)}</td>
                      <td className="px-3 py-2 tabular-nums">{formatPercent(c.cuota)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-8 text-center text-muted-foreground">
              {search ? "No se encontraron licitadores" : "Sin datos disponibles"}
            </p>
          )}
          {!isLoading && filteredSorted.length > 0 && (
            <>
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                Mostrando {filteredSorted.length} de {data?.competitors.length ?? 0} licitadores
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
