"use client";

/**
 * Tendencias — el corte temporal del dataset.
 *
 * Vista compartida por la ruta `/tendencias` y por `?vista=tiempo` del espacio
 * Mercado. El cuerpo no vive en el `page.tsx` de la ruta porque el espacio lo
 * montaba importando ese `page.tsx`: cada pantalla era a la vez boundary de
 * ruta y componente, con dos puntos de entrada y dos estados de URL, y Next no
 * podía tratarla como lo primero. Las otras siete vistas de Mercado siguen el
 * mismo reparto; el invariante lo fija `mercado/__tests__/views-shared.test.tsx`.
 */

import { useTendenciasView } from "../_hooks/use-tendencias-view";
import { TendenciasForecast } from "./tendencias-forecast";
import {
  TendenciasAcumulado,
  TendenciasHistograma,
  TendenciasVolumen,
  TendenciasWaterfall,
} from "./tendencias-graficos";
import { TendenciasHeatmap } from "./tendencias-heatmap";
import { TendenciasKpis } from "./tendencias-kpis";

export default function TendenciasView() {
  const {
    series,
    mesPico,
    waterfall,
    histBins,
    useLogScale,
    cumulativeData,
    heatmapData,
    totalCount,
    totalImporte,
    yoyCount,
    yoyImporte,
    forecast,
    forecastData,
    forecastLoading,
    forecastMetric,
    setForecastMetric,
    isLoading,
    error,
  } = useTendenciasView();

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center" role="alert">
        <p className="text-destructive">{"Error"}: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="sr-only">Tendencias</h1>
        <p className="text-muted-foreground">Evolución de publicaciones y montos a lo largo del tiempo.</p>
      </div>

      <TendenciasKpis
        totalCount={totalCount}
        totalImporte={totalImporte}
        yoyCount={yoyCount}
        yoyImporte={yoyImporte}
        mesPico={mesPico}
        isLoading={isLoading}
      />

      <TendenciasVolumen series={series} isLoading={isLoading} />

      <TendenciasAcumulado data={cumulativeData} isLoading={isLoading} />

      {waterfall.length > 0 && <TendenciasWaterfall data={waterfall} />}

      {histBins.length > 0 && (
        <TendenciasHistograma bins={histBins} useLogScale={useLogScale} />
      )}

      <TendenciasHeatmap heatmapData={heatmapData} isLoading={isLoading} />

      <TendenciasForecast
        forecast={forecast}
        data={forecastData}
        metric={forecastMetric}
        onMetricChange={setForecastMetric}
        isLoading={forecastLoading}
      />
    </div>
  );
}
