"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { MapPin, Hash, Trophy, ArrowUpDown } from "lucide-react";
import { Button } from "@/components/ui/button";
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

interface GeoItem {
  ccaa: string;
  count: number;
  importe: number;
  pct: number;
}

interface GeographyResponse {
  items: GeoItem[];
}

async function fetchGeography(): Promise<GeographyResponse> {
  const res = await fetch("/api/v1/analytics/geography", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch geography");
  return res.json();
}

const PIE_COLORS = [
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

type SortKey = "ccaa" | "count" | "importe" | "pct";
type SortDir = "asc" | "desc";

export default function GeografiaPage() {
  const [sortKey, setSortKey] = useState<SortKey>("count");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "geography"],
    queryFn: fetchGeography,
    staleTime: 5 * 60 * 1000,
  });

  const items = data?.items ?? [];

  const topCcaa = items.length > 0 ? items[0].ccaa : "-";
  const top3Concentration = useMemo(() => {
    if (items.length === 0) return 0;
    const total = items.reduce((s, i) => s + i.count, 0);
    const top3 = items.slice(0, 3).reduce((s, i) => s + i.count, 0);
    return total > 0 ? (top3 / total) * 100 : 0;
  }, [items]);

  const barData = useMemo(
    () => [...items].sort((a, b) => b.count - a.count),
    [items],
  );

  const pieData = useMemo(() => {
    const sorted = [...items].sort((a, b) => b.importe - a.importe);
    if (sorted.length <= 10) return sorted;
    const top = sorted.slice(0, 9);
    const rest = sorted.slice(9);
    const otherImporte = rest.reduce((s, i) => s + i.importe, 0);
    return [...top, { ccaa: "Otros", count: 0, importe: otherImporte, pct: 0 }];
  }, [items]);

  const sortedItems = useMemo(() => {
    const sorted = [...items];
    sorted.sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortDir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      }
      return sortDir === "asc" ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number);
    });
    return sorted;
  }, [items, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

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
        <h1 className="text-2xl font-bold tracking-tight">Geografia</h1>
        <p className="text-muted-foreground">
          Distribucion geografica por Comunidad Autonoma.
        </p>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          title="CCAA Mas Activa"
          value={isLoading ? undefined : topCcaa}
          icon={Trophy}
          loading={isLoading}
        />
        <KpiCard
          title="Concentracion Top 3"
          value={isLoading ? undefined : formatPercent(top3Concentration)}
          subtitle="del total"
          icon={MapPin}
          loading={isLoading}
        />
        <KpiCard
          title="Total CCAAs"
          value={isLoading ? undefined : formatNumber(items.length)}
          icon={Hash}
          loading={isLoading}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Horizontal Bar Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">CCAAs por Cantidad</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : barData.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(300, barData.length * 30)}>
                <BarChart data={barData} layout="vertical" margin={{ left: 120 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis
                    dataKey="ccaa"
                    type="category"
                    width={120}
                    tick={{ fontSize: 11 }}
                  />
                  <Tooltip
                    formatter={(value) => [formatNumber(value as number), "Licitaciones"]}
                  />
                  <Bar dataKey="count" fill="hsl(221, 83%, 53%)" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos</p>
            )}
          </CardContent>
        </Card>

        {/* Pie Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Distribucion por Importe</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height={400}>
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="importe"
                    nameKey="ccaa"
                    cx="50%"
                    cy="50%"
                    outerRadius={140}
                    label={({ name, percent }: { name?: string; percent?: number }) =>
                      `${name ?? ""} (${((percent ?? 0) * 100).toFixed(1)}%)`
                    }
                    labelLine={{ strokeWidth: 1 }}
                  >
                    {pieData.map((_, idx) => (
                      <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => formatCurrency(value as number)} />
                  <Legend />
                </PieChart>
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
          <CardTitle className="text-base">Todas las CCAAs</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
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
                        ["ccaa", "CCAA"],
                        ["count", "Cantidad"],
                        ["importe", "Importe"],
                        ["pct", "%"],
                      ] as [SortKey, string][]
                    ).map(([key, label]) => (
                      <th key={key} className={`pb-2 pr-4 font-medium text-muted-foreground ${key !== "ccaa" ? "text-right" : ""}`}>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-auto p-0 font-medium text-muted-foreground hover:text-foreground"
                          onClick={() => toggleSort(key)}
                        >
                          {label}
                          <ArrowUpDown className="ml-1 h-3 w-3" />
                        </Button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sortedItems.map((item, idx) => (
                    <tr key={idx} className="border-b border-border/50 hover:bg-muted/50">
                      <td className="py-2 pr-4 font-medium">{item.ccaa}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatNumber(item.count)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatCurrency(item.importe)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatPercent(item.pct)}</td>
                    </tr>
                  ))}
                  {sortedItems.length === 0 && (
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
