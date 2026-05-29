"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/charts/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { formatCurrency, formatNumber } from "@/lib/utils";
import { Handshake, Hash, Construction, Info } from "lucide-react";

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
  if (!res.ok) throw new Error("Error al cargar datos de competidores");
  return res.json();
}

export default function UtesPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "competitors"],
    queryFn: fetchCompetitors,
    staleTime: 5 * 60 * 1000,
  });

  const utes = useMemo(() => {
    if (!data?.competitors) return [];
    return data.competitors
      .filter((c) => {
        const upper = c.nombre.toUpperCase();
        return upper.includes("UTE") || upper.includes("UNION TEMPORAL") || upper.includes("UNIÓN TEMPORAL");
      })
      .sort((a, b) => b.importe - a.importe);
  }, [data]);

  const totalUtesImporte = useMemo(() => utes.reduce((s, c) => s + c.importe, 0), [utes]);
  const totalUtesCount = useMemo(() => utes.reduce((s, c) => s + c.count, 0), [utes]);

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
        <h1 className="text-2xl font-bold tracking-tight">UTEs</h1>
        <p className="text-muted-foreground">
          Analisis de Uniones Temporales de Empresas.
        </p>
      </div>

      {/* Development Banner */}
      <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/30">
        <Construction className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
        <div className="text-sm text-amber-800 dark:text-amber-300">
          <p className="font-medium">Analisis en desarrollo</p>
          <p className="mt-1 text-amber-700/80 dark:text-amber-400/80">
            La deteccion avanzada de UTEs (composicion de miembros, patrones de asociacion) se implementara
            en futuras versiones. Actualmente se muestran entidades detectadas por nombre.
          </p>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="UTEs Detectadas"
          value={isLoading ? undefined : formatNumber(utes.length)}
          icon={Handshake}
          loading={isLoading}
        />
        <KpiCard
          title="Adjudicaciones UTE"
          value={isLoading ? undefined : formatNumber(totalUtesCount)}
          icon={Hash}
          loading={isLoading}
        />
        <KpiCard
          title="Importe Total UTEs"
          value={isLoading ? undefined : formatCurrency(totalUtesImporte)}
          loading={isLoading}
        />
        <KpiCard
          title="% sobre Total"
          value={
            isLoading
              ? undefined
              : data?.total_adjudicaciones
                ? `${((totalUtesCount / data.total_adjudicaciones) * 100).toFixed(1)}%`
                : "0%"
          }
          loading={isLoading}
        />
      </div>

      {/* UTEs Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Handshake className="h-4 w-4" />
            UTEs Detectadas
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : utes.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="px-3 py-2 font-medium">#</th>
                    <th className="px-3 py-2 font-medium">Nombre</th>
                    <th className="px-3 py-2 font-medium">Adjudicaciones</th>
                    <th className="px-3 py-2 font-medium">Importe</th>
                  </tr>
                </thead>
                <tbody>
                  {utes.map((c, idx) => (
                    <tr key={idx} className="border-b last:border-0 hover:bg-muted/50">
                      <td className="px-3 py-2 text-muted-foreground">{idx + 1}</td>
                      <td className="px-3 py-2 font-medium">
                        <div className="flex items-center gap-2">
                          {c.nombre}
                          <Badge variant="outline" className="text-[10px]">UTE</Badge>
                        </div>
                      </td>
                      <td className="px-3 py-2 tabular-nums">{formatNumber(c.count)}</td>
                      <td className="px-3 py-2 tabular-nums">{formatCurrency(c.importe)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Separator className="my-3" />
              <p className="text-xs text-muted-foreground">
                {utes.length} UTEs detectadas en los datos
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Info className="h-10 w-10 text-muted-foreground/50 mb-3" />
              <p className="text-muted-foreground">
                No se han detectado UTEs en los datos actuales
              </p>
              <p className="text-xs text-muted-foreground/70 mt-1">
                Se buscan entidades con &quot;UTE&quot; o &quot;UNION TEMPORAL&quot; en su nombre
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
