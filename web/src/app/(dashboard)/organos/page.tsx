"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { Building2, Hash, Trophy, BarChart3, Search } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Treemap,
} from "recharts";

interface OrganoItem {
  organo_contratacion: string;
  count: number;
  importe: number;
  pct: number;
  ccaa?: string;
}

interface OrganosResponse {
  items: OrganoItem[];
  total: number;
}

async function fetchOrganos(): Promise<OrganosResponse> {
  const res = await fetch("/api/v1/analytics/organos", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch organos");
  return res.json();
}

const COLORS = [
  "hsl(221, 83%, 53%)",
  "hsl(262, 83%, 58%)",
  "hsl(160, 60%, 45%)",
  "hsl(38, 92%, 50%)",
  "hsl(0, 72%, 51%)",
  "hsl(199, 89%, 48%)",
  "hsl(43, 96%, 56%)",
  "hsl(280, 65%, 60%)",
];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CustomTreemapContent(props: any) {
  const { x, y, width, height, name, value } = props;
  if (width < 40 || height < 25) return null;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={COLORS[props.index % COLORS.length]} rx={4} opacity={0.85} />
      <text x={x + 6} y={y + 16} fill="#fff" fontSize={11} fontWeight={600}>
        {width > 80 ? (name?.slice(0, 25) ?? "") : (name?.slice(0, 10) ?? "")}
      </text>
      {height > 38 && (
        <text x={x + 6} y={y + 30} fill="#ffffffcc" fontSize={10}>
          {formatCurrency(value)}
        </text>
      )}
    </g>
  );
}

export default function OrganosPage() {
  const [filter, setFilter] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "organos"],
    queryFn: fetchOrganos,
    staleTime: 5 * 60 * 1000,
  });

  const items = data?.items ?? [];

  const top10Concentration = useMemo(() => {
    if (items.length === 0) return 0;
    const totalCount = items.reduce((s, i) => s + i.count, 0);
    const top10Count = items.slice(0, 10).reduce((s, i) => s + i.count, 0);
    return totalCount > 0 ? (top10Count / totalCount) * 100 : 0;
  }, [items]);

  const topOrgano = items.length > 0 ? items[0].organo_contratacion : "-";

  const top20 = useMemo(() => items.slice(0, 20), [items]);

  const treemapData = useMemo(
    () =>
      items
        .filter((i) => i.importe > 0)
        .slice(0, 30)
        .map((i) => ({
          name: i.organo_contratacion,
          size: i.importe,
        })),
    [items],
  );

  const filteredItems = useMemo(() => {
    if (!filter) return items;
    const q = filter.toLowerCase();
    return items.filter(
      (i) =>
        i.organo_contratacion.toLowerCase().includes(q) ||
        (i.ccaa && i.ccaa.toLowerCase().includes(q)),
    );
  }, [items, filter]);

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
        <h1 className="text-2xl font-bold tracking-tight">Organos</h1>
        <p className="text-muted-foreground">
          Ranking de organos de contratacion.
        </p>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          title="Total Organos"
          value={isLoading ? undefined : formatNumber(data?.total ?? items.length)}
          icon={Building2}
          loading={isLoading}
        />
        <KpiCard
          title="Concentracion Top 10"
          value={isLoading ? undefined : formatPercent(top10Concentration)}
          subtitle="del total de licitaciones"
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Top Organo"
          value={isLoading ? undefined : topOrgano.length > 40 ? topOrgano.slice(0, 40) + "..." : topOrgano}
          icon={Trophy}
          loading={isLoading}
        />
      </div>

      {/* Horizontal Bar Chart: Top 20 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BarChart3 className="h-4 w-4" />
            Top 20 Organos por Cantidad
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[500px] w-full" />
          ) : top20.length > 0 ? (
            <ResponsiveContainer width="100%" height={Math.max(400, top20.length * 28)}>
              <BarChart data={top20} layout="vertical" margin={{ left: 200 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis
                  dataKey="organo_contratacion"
                  type="category"
                  width={200}
                  tick={{ fontSize: 10 }}
                  tickFormatter={(v: string) => v.length > 35 ? v.slice(0, 35) + "..." : v}
                />
                <Tooltip
                  formatter={(value) => [formatNumber(value as number), "Licitaciones"]}
                  labelFormatter={(label) => label}
                />
                <Bar dataKey="count" fill="hsl(221, 83%, 53%)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="py-12 text-center text-muted-foreground">Sin datos</p>
          )}
        </CardContent>
      </Card>

      {/* Treemap: by importe */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Organos por Importe</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : treemapData.length > 0 ? (
            <ResponsiveContainer width="100%" height={400}>
              <Treemap
                data={treemapData}
                dataKey="size"
                nameKey="name"
                content={<CustomTreemapContent />}
              />
            </ResponsiveContainer>
          ) : (
            <p className="py-12 text-center text-muted-foreground">Sin datos de importe</p>
          )}
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Listado Completo</CardTitle>
          <div className="relative mt-2">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Buscar organo..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="pl-9 max-w-sm"
            />
          </div>
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
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-2 pr-4 font-medium text-muted-foreground">Organo</th>
                    <th className="pb-2 pr-4 font-medium text-muted-foreground text-right">Cantidad</th>
                    <th className="pb-2 pr-4 font-medium text-muted-foreground text-right">Importe</th>
                    <th className="pb-2 pr-4 font-medium text-muted-foreground text-right">%</th>
                    <th className="pb-2 font-medium text-muted-foreground">CCAA</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((item, idx) => (
                    <tr key={idx} className="border-b border-border/50 hover:bg-muted/50">
                      <td className="py-2 pr-4 max-w-xs truncate" title={item.organo_contratacion}>
                        {item.organo_contratacion}
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatNumber(item.count)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatCurrency(item.importe)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatPercent(item.pct)}</td>
                      <td className="py-2">
                        {item.ccaa ? <Badge variant="secondary">{item.ccaa}</Badge> : "-"}
                      </td>
                    </tr>
                  ))}
                  {filteredItems.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-muted-foreground">
                        Sin resultados
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
