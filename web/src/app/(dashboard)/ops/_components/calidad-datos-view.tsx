"use client";

/**
 * Calidad de datos — completitud y consistencia del dataset.
 *
 * Vista compartida por la ruta `/calidad-datos` y por `?vista=calidad` del
 * espacio Ops. Ver la nota en `observabilidad-view.tsx` sobre por qué el
 * cuerpo no vive en el `page.tsx` de la ruta.
 *
 * Aquí queda el orden de la pantalla. La llamada y sus derivaciones están en
 * `_hooks/use-calidad-datos.ts`, las reglas de abstención —qué se pinta y qué
 * no cuando el backend no mide— en `calidad-datos/quality-data.ts`, y cada
 * bloque en su fichero de `calidad-datos/`.
 */

import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { CalibracionBajaBlock } from "@/components/calibracion-baja";
import { SourceFreshnessPanel } from "@/components/source-freshness-panel";
import { useCalidadDatos } from "../_hooks/use-calidad-datos";
import { CalidadKpis } from "./calidad-datos/calidad-kpis";
import { CompletitudCard } from "./calidad-datos/completitud-card";
import { DlqFrescuraCards } from "./calidad-datos/dlq-frescura-cards";
import { FormatoFechaCard } from "./calidad-datos/formato-fecha-card";
import { PipelineCard } from "./calidad-datos/pipeline-card";

export default function CalidadDatosView() {
  const { data, isLoading, isError, hoursAgo, freshness, chartData, dlqCount, fechasNoIso } =
    useCalidadDatos();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="sr-only">Calidad de Datos</h1>
        <p className="text-muted-foreground">
          Completitud y consistencia del dataset.
        </p>
      </div>

      {isError && (
        <Card className="border-destructive">
          <CardContent className="pt-6 text-destructive">
            Error al cargar métricas de calidad. Verifica que la API esté activa.
          </CardContent>
        </Card>
      )}

      <CalidadKpis
        data={data}
        isLoading={isLoading}
        hoursAgo={hoursAgo}
        freshness={freshness}
      />

      <Separator />

      <SourceFreshnessPanel />

      <CompletitudCard data={chartData} isLoading={isLoading} />

      <FormatoFechaCard
        pctIso={data?.pct_fecha_iso}
        fechasNoIso={fechasNoIso}
        isLoading={isLoading}
      />

      <DlqFrescuraCards
        dlqCount={dlqCount}
        hoursAgo={hoursAgo}
        freshness={freshness}
        isLoading={isLoading}
      />

      <PipelineCard totalRecords={data?.total_records} isLoading={isLoading} />

      {/* Calibración del modelo de baja — closed loop predicción vs. realidad */}
      <CalibracionBajaBlock />
    </div>
  );
}
