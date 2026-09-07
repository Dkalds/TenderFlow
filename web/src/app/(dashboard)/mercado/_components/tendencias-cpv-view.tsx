"use client";

/**
 * Vista compartida por la ruta `/tendencias-cpv` y por `?vista=cpv` del espacio
 * Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo no vive
 * en el `page.tsx` de la ruta.
 */

import { useTendenciasCpvView } from "../_hooks/use-tendencias-cpv-view";
import {
  TendenciasCpvForecast,
  TendenciasCpvSeries,
  TendenciasCpvTop,
} from "./tendencias-cpv-graficos";
import { TendenciasCpvSelector } from "./tendencias-cpv-selector";
import { TendenciasCpvTabla } from "./tendencias-cpv-tabla";

export default function TendenciasCpvView() {
  const {
    allCpvs,
    topCpvs,
    effectiveCpvs,
    toggleCpv,
    chartData,
    forecastData,
    forecastLoading,
    showForecast,
    setShowForecast,
    cpvTableData,
    isLoading,
    error,
  } = useTendenciasCpvView();

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
        <h1 className="sr-only">Tendencias CPV</h1>
        <p className="text-muted-foreground">Series temporales por código CPV.</p>
      </div>

      <TendenciasCpvSelector
        allCpvs={allCpvs}
        effectiveCpvs={effectiveCpvs}
        onToggle={toggleCpv}
        isLoading={isLoading}
      />

      <TendenciasCpvSeries
        allCpvs={allCpvs}
        effectiveCpvs={effectiveCpvs}
        data={chartData}
        showForecast={showForecast}
        onToggleForecast={() => setShowForecast((f) => !f)}
        isLoading={isLoading}
      />

      {showForecast && (
        <TendenciasCpvForecast data={forecastData} isLoading={forecastLoading} />
      )}

      <TendenciasCpvTop topCpvs={topCpvs} isLoading={isLoading} />

      <TendenciasCpvTabla filas={cpvTableData} onToggle={toggleCpv} isLoading={isLoading} />
    </div>
  );
}
