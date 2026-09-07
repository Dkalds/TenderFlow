"use client";

/**
 * Los cinco gráficos de Tecnologías: la evolución mensual (con su conmutador
 * conteo/importe), las dos barras complementarias —volumen coloreado por
 * importe e importe coloreado por volumen— y el par donut + distribución
 * geográfica.
 */

import dynamic from "next/dynamic";

import { EmptyState } from "@/components/ui/empty-state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { TrendingUp, Map as MapIcon } from "lucide-react";

import type {
  BarItem,
  TecnologiaItem,
  TrendMetric,
} from "../_hooks/use-tecnologias-view";

const TecnologiasEvolutionChart = dynamic(() => import("@/components/charts/tecnologias-charts").then(m => ({ default: m.TecnologiasEvolutionChart })), { ssr: false, loading: () => <Skeleton className="h-[340px] w-full rounded-md" /> });
const TecnologiasVolumeBarChart = dynamic(() => import("@/components/charts/tecnologias-charts").then(m => ({ default: m.TecnologiasVolumeBarChart })), { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-md" /> });
const TecnologiasImporteBarChart = dynamic(() => import("@/components/charts/tecnologias-charts").then(m => ({ default: m.TecnologiasImporteBarChart })), { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-md" /> });
const TecnologiasDonutChart = dynamic(() => import("@/components/charts/tecnologias-charts").then(m => ({ default: m.TecnologiasDonutChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });
const TecnologiasGeoBarChart = dynamic(() => import("@/components/charts/tecnologias-charts").then(m => ({ default: m.TecnologiasGeoBarChart })), { ssr: false, loading: () => <Skeleton className="h-[400px] w-full rounded-md" /> });

export function TecnologiasEvolucion({
  data,
  techs,
  trendMetric,
  onTrendMetricChange,
  isLoading,
}: {
  data: Record<string, number | string>[];
  techs: string[];
  trendMetric: TrendMetric;
  onTrendMetricChange: (metric: TrendMetric) => void;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <TrendingUp className="h-4 w-4" />
            Evolución mensual por tecnología
          </CardTitle>
          <div className="flex gap-1">
            <Button
              variant={trendMetric === "count" ? "default" : "outline"}
              size="sm"
              onClick={() => onTrendMetricChange("count")}
            >
              Conteo
            </Button>
            <Button
              variant={trendMetric === "importe" ? "default" : "outline"}
              size="sm"
              onClick={() => onTrendMetricChange("importe")}
            >
              Importe
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-[340px] w-full" />
        ) : data.length > 0 && techs.length > 0 ? (
          <TecnologiasEvolutionChart data={data} techs={techs} trendMetric={trendMetric} />
        ) : (
          <EmptyState />
        )}
      </CardContent>
    </Card>
  );
}

export function TecnologiasBarras({
  volumeBar,
  importeBar,
  isLoading,
}: {
  volumeBar: BarItem[];
  importeBar: BarItem[];
  isLoading: boolean;
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Volumen por tecnología</CardTitle>
          <CardDescription>Nº de licitaciones (color = importe)</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[420px] w-full" />
          ) : volumeBar.length > 0 ? (
            <TecnologiasVolumeBarChart data={volumeBar} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Importe por tecnología</CardTitle>
          <CardDescription>Importe acumulado (color = nº licitaciones)</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[420px] w-full" />
          ) : importeBar.length > 0 ? (
            <TecnologiasImporteBarChart data={importeBar} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function TecnologiasDistribucion({
  donutData,
  geoData,
  geoTechs,
  isLoading,
}: {
  donutData: TecnologiaItem[];
  geoData: Record<string, number | string>[];
  geoTechs: string[];
  isLoading: boolean;
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Distribución por cantidad</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : donutData.length > 0 ? (
            <TecnologiasDonutChart data={donutData} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <MapIcon className="h-4 w-4" />
            Distribución geográfica por tecnología
          </CardTitle>
          <CardDescription>Top 10 CCAA</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[400px] w-full" />
          ) : geoData.length > 0 && geoTechs.length > 0 ? (
            <TecnologiasGeoBarChart data={geoData} techs={geoTechs} />
          ) : (
            <EmptyState />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
