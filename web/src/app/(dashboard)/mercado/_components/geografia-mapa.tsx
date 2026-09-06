"use client";

/**
 * El coropleto de España, con el conmutador licitaciones/importe.
 *
 * `SpainMap` monta Leaflet, que toca `window` al construir el mapa y carga su
 * CSS como side-effect: por eso entra por `next/dynamic` con `ssr: false` y con
 * un skeleton del mismo alto, para que el layout no salte al hidratar.
 */

import dynamic from "next/dynamic";
import { Map } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import type { MapMetric } from "../_hooks/use-geografia-view";

const SpainMap = dynamic(() => import("@/components/charts/spain-map").then(m => ({ default: m.SpainMap })), { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-md" /> });

export function GeografiaMapa({
  data,
  metric,
  onMetricChange,
  onCcaaClick,
  isLoading,
}: {
  data: { ccaa: string; value: number }[];
  metric: MapMetric;
  onMetricChange: (metric: MapMetric) => void;
  onCcaaClick: (ccaa: string) => void;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <Map className="h-4 w-4" />
            Mapa por {metric === "count" ? "Licitaciones" : "Importe"}
          </CardTitle>
        <div className="flex items-center gap-1 rounded-lg border p-0.5">
            <Button
              size="sm"
              variant={metric === "count" ? "default" : "ghost"}
              className="h-7 px-3 text-xs"
              onClick={() => onMetricChange("count")}
            >
              Licitaciones
            </Button>
            <Button
              size="sm"
              variant={metric === "importe" ? "default" : "ghost"}
              className="h-7 px-3 text-xs"
              onClick={() => onMetricChange("importe")}
            >
              Importe €
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[500px] w-full" />
        ) : (
          <SpainMap
            data={data}
            metric={metric === "count" ? "Licitaciones" : "Importe €"}
            height={480}
            onCcaaClick={onCcaaClick}
          />
        )}
      </CardContent>
    </Card>
  );
}
