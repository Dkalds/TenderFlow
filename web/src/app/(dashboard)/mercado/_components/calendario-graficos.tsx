"use client";

/**
 * Los dos gráficos que acompañan al heatmap del Calendario: el total por mes y
 * el promedio por día de la semana.
 *
 * Los dos títulos llevan el año seleccionado porque las dos cifras dependen de
 * él: sin ese universo declarado, «media de 12 publicaciones el martes» no dice
 * de cuándo (ADR-014).
 */

import dynamic from "next/dynamic";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";

import type { DowPoint, MonthlyPoint } from "../_hooks/use-calendario-view";

const CalendarioMonthlyChart = dynamic(() => import("@/components/charts/calendario-charts").then(m => ({ default: m.CalendarioMonthlyChart })), { ssr: false, loading: () => <Skeleton className="h-[300px] w-full rounded-md" /> });
const CalendarioDowChart = dynamic(() => import("@/components/charts/calendario-charts").then(m => ({ default: m.CalendarioDowChart })), { ssr: false, loading: () => <Skeleton className="h-[200px] w-full rounded-md" /> });

export function CalendarioMensual({
  data,
  selectedYear,
  isLoading,
}: {
  data: MonthlyPoint[];
  selectedYear: number;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Publicaciones por Mes — {selectedYear}</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[300px] w-full" />
        ) : data.length > 0 ? (
          <CalendarioMonthlyChart data={data} />
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}

export function CalendarioDiaSemana({
  data,
  selectedYear,
  isLoading,
}: {
  data: DowPoint[];
  selectedYear: number;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Distribución por Día de la Semana — {selectedYear}</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[200px] w-full" />
        ) : data.some((d) => d.promedio > 0) ? (
          <CalendarioDowChart data={data} />
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}
