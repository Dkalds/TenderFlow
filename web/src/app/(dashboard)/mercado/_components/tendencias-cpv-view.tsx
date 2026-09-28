"use client";

/**
 * Vista compartida por la ruta `/tendencias-cpv` y por `?vista=cpv` del espacio
 * Mercado. Ver la nota en `tendencias-view.tsx` sobre por qué el cuerpo no vive
 * en el `page.tsx` de la ruta.
 */

import { PanelError } from "@/components/console/panel";

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
    forecastCpv,
    forecastCpvRespuesta,
    forecastCpvOptions,
    setForecastCpv,
    showForecast,
    setShowForecast,
    cpvTableData,
    isLoading,
    error,
    refetch,
  } = useTendenciasCpvView();

  if (error) {
    return <PanelError title="No se pudieron cargar las tendencias por CPV" error={error} onRetry={refetch} />;
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="sr-only">Tendencias por CPV</h1>
        <p className="text-tf-meta text-muted-foreground">
          Cómo evoluciona el importe de cada código CPV.
        </p>
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
        <TendenciasCpvForecast
          data={forecastData}
          cpv={forecastCpv}
          cpvRespuesta={forecastCpvRespuesta}
          opciones={forecastCpvOptions}
          onCpvChange={setForecastCpv}
          isLoading={forecastLoading}
        />
      )}

      <TendenciasCpvTop topCpvs={topCpvs} isLoading={isLoading} />

      <TendenciasCpvTabla filas={cpvTableData} onToggle={toggleCpv} isLoading={isLoading} />
    </div>
  );
}
