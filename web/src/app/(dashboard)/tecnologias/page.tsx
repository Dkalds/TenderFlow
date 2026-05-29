"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { Cpu, Hash, AlertTriangle, Trophy, Search } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";

interface TecnologiaItem {
  tecnologia: string;
  count: number;
  importe: number;
  pct: number;
}

interface TecnologiasResponse {
  items: TecnologiaItem[];
  total: number;
  sin_clasificar: number;
}

async function fetchTecnologias(): Promise<TecnologiasResponse> {
  const res = await fetch("/api/v1/analytics/tecnologias", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch tecnologias");
  return res.json();
}

const DONUT_COLORS = [
  "hsl(221, 83%, 53%)",
  "hsl(160, 60%, 45%)",
  "hsl(38, 92%, 50%)",
  "hsl(0, 72%, 51%)",
  "hsl(262, 83%, 58%)",
  "hsl(199, 89%, 48%)",
  "hsl(43, 96%, 56%)",
  "hsl(280, 65%, 60%)",
  "hsl(330, 70%, 55%)",
  "hsl(180, 55%, 45%)",
  "hsl(15, 80%, 55%)",
  "hsl(90, 55%, 45%)",
];

export default function TecnologiasPage() {
  const [filter, setFilter] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "tecnologias"],
    queryFn: fetchTecnologias,
    staleTime: 5 * 60 * 1000,
  });

  const items = data?.items ?? [];
  const topTech = items.length > 0 ? items[0].tecnologia : "-";

  const donutData = useMemo(() => {
    const sorted = [...items].sort((a, b) => b.count - a.count);
    if (sorted.length <= 10) return sorted;
    const top = sorted.slice(0, 9);
    const rest = sorted.slice(9);
    return [
      ...top,
      {
        tecnologia: "Otros",
        count: rest.reduce((s, i) => s + i.count, 0),
        importe: rest.reduce((s, i) => s + i.importe, 0),
        pct: rest.reduce((s, i) => s + i.pct, 0),
      },
    ];
  }, [items]);

  const barData = useMemo(
    () =>
      [...items]
        .filter((i) => i.importe > 0)
        .sort((a, b) => b.importe - a.importe)
        .slice(0, 20),
    [items],
  );

  const filteredItems = useMemo(() => {
    if (!filter) return items;
    const q = filter.toLowerCase();
    return items.filter((i) => i.tecnologia.toLowerCase().includes(q));
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
        <h1 className="text-2xl font-bold tracking-tight">Tecnologias</h1>
        <p className="text-muted-foreground">
          Distribucion y tendencias de tecnologias mencionadas.
        </p>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          title="Total Tecnologias"
          value={isLoading ? undefined : formatNumber(data?.total ?? items.length)}
          icon={Cpu}
          loading={isLoading}
        />
        <KpiCard
          title="Sin Clasificar"
          value={isLoading ? undefined : formatNumber(data?.sin_clasificar ?? 0)}
          icon={AlertTriangle}
          loading={isLoading}
        />
        <KpiCard
          title="Top Tecnologia"
          value={isLoading ? undefined : topTech}
          icon={Trophy}
          loading={isLoading}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Donut Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Distribucion por Cantidad</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : donutData.length > 0 ? (
              <ResponsiveContainer width="100%" height={400}>
                <PieChart>
                  <Pie
                    data={donutData}
                    dataKey="count"
                    nameKey="tecnologia"
                    cx="50%"
                    cy="50%"
                    innerRadius={70}
                    outerRadius={140}
                    label={({ name, percent }: { name?: string; percent?: number }) =>
                      `${name ?? ""} (${((percent ?? 0) * 100).toFixed(1)}%)`
                    }
                    labelLine={{ strokeWidth: 1 }}
                  >
                    {donutData.map((_, idx) => (
                      <Cell key={idx} fill={DONUT_COLORS[idx % DONUT_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => formatNumber(value as number)} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos</p>
            )}
          </CardContent>
        </Card>

        {/* Bar Chart: by importe */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top 20 por Importe</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : barData.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(300, barData.length * 28)}>
                <BarChart data={barData} layout="vertical" margin={{ left: 100 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v: number) => formatCurrency(v)}
                  />
                  <YAxis
                    dataKey="tecnologia"
                    type="category"
                    width={100}
                    tick={{ fontSize: 11 }}
                  />
                  <Tooltip
                    formatter={(value) => [formatCurrency(value as number), "Importe"]}
                  />
                  <Bar dataKey="importe" fill="hsl(160, 60%, 45%)" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Todas las Tecnologias</CardTitle>
          <div className="relative mt-2">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Buscar tecnologia..."
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
                    <th className="pb-2 pr-4 font-medium text-muted-foreground">Tecnologia</th>
                    <th className="pb-2 pr-4 font-medium text-muted-foreground text-right">Cantidad</th>
                    <th className="pb-2 pr-4 font-medium text-muted-foreground text-right">Importe</th>
                    <th className="pb-2 font-medium text-muted-foreground text-right">%</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((item, idx) => (
                    <tr key={idx} className="border-b border-border/50 hover:bg-muted/50">
                      <td className="py-2 pr-4 font-medium">{item.tecnologia}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatNumber(item.count)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatCurrency(item.importe)}</td>
                      <td className="py-2 text-right tabular-nums">{formatPercent(item.pct)}</td>
                    </tr>
                  ))}
                  {filteredItems.length === 0 && (
                    <tr>
                      <td colSpan={4} className="py-8 text-center text-muted-foreground">
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
