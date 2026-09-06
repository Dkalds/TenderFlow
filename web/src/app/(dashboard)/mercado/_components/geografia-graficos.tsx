"use client";

/**
 * El par de gráficos de Geografía: barras por cantidad y donut por importe.
 * Los dos son también controles de filtro — un clic marca esa CCAA en el ámbito
 * global, igual que la tabla y el mapa.
 */

import dynamic from "next/dynamic";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";

import type { GeoItem } from "../_hooks/use-geografia-view";

const GeografiaBarChart = dynamic(() => import("@/components/charts/geografia-charts").then(m => ({ default: m.GeografiaBarChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const GeografiaPieChart = dynamic(() => import("@/components/charts/geografia-charts").then(m => ({ default: m.GeografiaPieChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });

export function GeografiaGraficos({
  barData,
  pieData,
  onSelect,
  isLoading,
}: {
  barData: GeoItem[];
  /** Top 9 por importe más el bucket «Otros» cuando hay más de diez CCAA. */
  pieData: GeoItem[];
  onSelect: (ccaa: string) => void;
  isLoading: boolean;
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {/* Horizontal Bar Chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">CCAAs por Cantidad</CardTitle>
          <CardDescription>Clic en una CCAA para filtrar</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : barData.length > 0 ? (
            <GeografiaBarChart data={barData} onSelect={onSelect} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      {/* Pie Chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Distribución por Importe
          </CardTitle>
          <CardDescription>Clic en una CCAA para filtrar</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : pieData.length > 0 ? (
            <GeografiaPieChart data={pieData} onSelect={onSelect} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
