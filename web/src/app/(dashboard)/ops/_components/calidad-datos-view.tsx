"use client";

/**
 * Datos — completitud y consistencia del dato que entra.
 *
 * El módulo conserva el nombre de la ruta que absorbió (`/calidad-datos`
 * redirige a `?vista=calidad`); la pestaña se llama «Datos».
 *
 * Aquí queda el orden de la pantalla. La llamada y sus derivaciones están en
 * `_hooks/use-calidad-datos.ts`, las reglas de abstención —qué se pinta y qué
 * no cuando el backend no mide— en `calidad-datos/quality-data.ts`, y cada
 * bloque en su fichero de `calidad-datos/`.
 *
 * Lo que ya no está, y por qué:
 *
 * - La tira de cuatro cifras de cabecera. Dos («Cobertura de NIF» y «de módulo
 *   SAP») no las mide el backend y salían siempre «sin medir»; las otras dos
 *   —registros totales y frescura— se repetían más abajo.
 * - La cola de errores y la frescura de la ingesta: están en la tira de salud,
 *   encima de todas las vistas, y la cola se trabaja en Ejecuciones.
 * - «Resumen de la ingesta», que era el total de registros otra vez: ahora va
 *   en el pie del gráfico de completitud, que es de lo que es denominador.
 */

import { PanelError } from "@/components/console/panel";
import { CalibracionBajaBlock } from "@/components/calibracion-baja";
import { SourceFreshnessPanel } from "@/components/source-freshness-panel";
import { useCalidadDatos } from "../_hooks/use-calidad-datos";
import { CompletitudCard } from "./calidad-datos/completitud-card";
import { FormatoFechaCard } from "./calidad-datos/formato-fecha-card";
import { ReportesCard } from "./calidad-datos/reportes-card";
import { TendenciaCompletitudCard } from "./calidad-datos/tendencia-completitud-card";

export default function CalidadDatosView() {
  const { data, isLoading, error, refetch, chartData, fechasNoIso } = useCalidadDatos();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="sr-only">Datos</h1>
        <p className="text-tf-meta text-muted-foreground">
          Si cada fuente llega a tiempo y si lo que trae viene completo.
        </p>
      </div>

      <SourceFreshnessPanel />

      {/* Con la consulta caída, los paneles de calidad no se pintan: sus ceros
          por defecto afirmarían algo que nadie midió. */}
      {error ? (
        <PanelError
          title="No se pudieron cargar las métricas de calidad"
          error={error}
          onRetry={refetch}
        />
      ) : (
        <>
          <CompletitudCard data={chartData} totalRecords={data?.total_records} isLoading={isLoading} />

          <TendenciaCompletitudCard serie={data?.tendencia_completitud} isLoading={isLoading} />

          <FormatoFechaCard pctIso={data?.pct_fecha_iso} fechasNoIso={fechasNoIso} isLoading={isLoading} />

          <ReportesCard reportes={data?.reportes_por_tipo} isLoading={isLoading} />
        </>
      )}

      {/* Calibración del modelo de baja — closed loop predicción vs. realidad */}
      <CalibracionBajaBlock />
    </div>
  );
}
