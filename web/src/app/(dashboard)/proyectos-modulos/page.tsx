"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { FolderKanban, Hash, Boxes, Layers } from "lucide-react";
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

interface ModuloItem {
  modulo: string;
  count: number;
  importe: number;
}

interface TipoProyectoItem {
  tipo: string;
  count: number;
  importe: number;
}

interface ProyectosModulosResponse {
  modulos: ModuloItem[];
  tipos_proyecto: TipoProyectoItem[];
  total_clasificados: number;
  total_modulos: number;
  total_tipos: number;
}

async function fetchProyectosModulos(): Promise<ProyectosModulosResponse> {
  const res = await fetch("/api/v1/analytics/proyectos-modulos", {
    credentials: "include",
  });
  if (!res.ok) throw new Error("Failed to fetch proyectos-modulos");
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
];

export default function ProyectosModulosPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "proyectos-modulos"],
    queryFn: fetchProyectosModulos,
    staleTime: 5 * 60 * 1000,
  });

  const modulos = data?.modulos ?? [];
  const tipos = data?.tipos_proyecto ?? [];

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
        <h1 className="text-2xl font-bold tracking-tight">Proyectos &amp; Modulos</h1>
        <p className="text-muted-foreground">
          Desglose por tipo de proyecto y modulo SAP.
        </p>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          title="Total Clasificados"
          value={isLoading ? undefined : formatNumber(data?.total_clasificados ?? 0)}
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Modulos Detectados"
          value={isLoading ? undefined : formatNumber(data?.total_modulos ?? modulos.length)}
          icon={Boxes}
          loading={isLoading}
        />
        <KpiCard
          title="Tipos de Proyecto"
          value={isLoading ? undefined : formatNumber(data?.total_tipos ?? tipos.length)}
          icon={Layers}
          loading={isLoading}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Bar Chart: SAP Modules */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <FolderKanban className="h-4 w-4" />
              Modulos SAP por Cantidad
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-[400px] w-full" />
            ) : modulosSorted.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(300, modulosSorted.length * 30)}>
                <BarChart data={modulosSorted} layout="vertical" margin={{ left: 80 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis
                    dataKey="modulo"
                    type="category"
                    width={80}
                    tick={{ fontSize: 11 }}
                  />
                  <Tooltip
                    formatter={(value) => [formatNumber(value as number), "Licitaciones"]}
                  />
                  <Bar dataKey="count" fill="hsl(262, 83%, 58%)" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="py-12 text-center text-muted-foreground">Sin datos</p>
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
              <ResponsiveContainer width="100%" height={400}>
                <PieChart>
                  <Pie
                    data={tiposPie}
                    dataKey="count"
                    nameKey="tipo"
                    cx="50%"
                    cy="50%"
                    outerRadius={140}
                    label={({ name, percent }: { name?: string; percent?: number }) =>
                      `${name ?? ""} (${((percent ?? 0) * 100).toFixed(1)}%)`
                    }
                    labelLine={{ strokeWidth: 1 }}
                  >
                    {tiposPie.map((_, idx) => (
                      <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
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
      </div>

      {/* Modules Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Modulos SAP</CardTitle>
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
                    <th className="pb-2 pr-4 font-medium text-muted-foreground">Modulo</th>
                    <th className="pb-2 pr-4 font-medium text-muted-foreground text-right">Cantidad</th>
                    <th className="pb-2 font-medium text-muted-foreground text-right">Importe</th>
                  </tr>
                </thead>
                <tbody>
                  {modulosSorted.map((item, idx) => (
                    <tr key={idx} className="border-b border-border/50 hover:bg-muted/50">
                      <td className="py-2 pr-4 font-medium">{item.modulo}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatNumber(item.count)}</td>
                      <td className="py-2 text-right tabular-nums">{formatCurrency(item.importe)}</td>
                    </tr>
                  ))}
                  {modulosSorted.length === 0 && (
                    <tr>
                      <td colSpan={3} className="py-8 text-center text-muted-foreground">Sin datos</td>
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
                    <th className="pb-2 pr-4 font-medium text-muted-foreground">Tipo</th>
                    <th className="pb-2 pr-4 font-medium text-muted-foreground text-right">Cantidad</th>
                    <th className="pb-2 font-medium text-muted-foreground text-right">Importe</th>
                  </tr>
                </thead>
                <tbody>
                  {[...tipos].sort((a, b) => b.count - a.count).map((item, idx) => (
                    <tr key={idx} className="border-b border-border/50 hover:bg-muted/50">
                      <td className="py-2 pr-4 font-medium">{item.tipo}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatNumber(item.count)}</td>
                      <td className="py-2 text-right tabular-nums">{formatCurrency(item.importe)}</td>
                    </tr>
                  ))}
                  {tipos.length === 0 && (
                    <tr>
                      <td colSpan={3} className="py-8 text-center text-muted-foreground">Sin datos</td>
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
