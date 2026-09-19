"use client";

/**
 * Tendencia de completitud por mes de publicación (RFC ux-calidad-datos #3).
 *
 * Cada punto es la cohorte de expedientes publicados ese mes, medida HOY: no
 * es un histórico de snapshots (no hay tabla que lo guarde), y la descripción
 * lo dice para que nadie lea «en marzo el CPV estaba al 80 %». Lo que sí
 * detecta es lo que el RFC pedía: si los expedientes de los últimos meses
 * llegan con menos campos que los anteriores —un cambio de esquema de la
 * fuente—, la curva cae a partir de ese mes. Sin serie, la tarjeta se abstiene.
 */

import dynamic from "next/dynamic";
import { TrendingUp } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";

import type { CompletitudMes } from "./quality-data";

const CalidadTendenciaChart = dynamic(
  () =>
    import("@/components/charts/calidad-datos-charts").then((m) => ({
      default: m.CalidadTendenciaChart,
    })),
  { ssr: false, loading: () => <Skeleton className="h-[260px] w-full rounded-md" /> },
);

export function TendenciaCompletitudCard({
  serie,
  isLoading,
}: {
  serie: CompletitudMes[] | undefined;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5" aria-hidden="true" />
          Tendencia de completitud
        </CardTitle>
        <CardDescription>
          % de expedientes con cada campo, por mes de publicación (últimos 12 meses), medido hoy.
          Una caída desde un mes concreto apunta a un cambio en la fuente.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[260px] w-full" />
        ) : serie && serie.length > 0 ? (
          <CalidadTendenciaChart data={serie} />
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}
