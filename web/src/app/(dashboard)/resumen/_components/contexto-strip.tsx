"use client";

import { useMemo } from "react";
import { PanelError } from "@/components/console/panel";
import { useFilteredQuery } from "@/hooks/use-filtered-query";
import { celdaSalud, coberturaSinMedir } from "@/lib/cobertura";
import type { CeldaSalud, CoberturaMetrica } from "@/lib/cobertura";
import { compararMeses, mesesCerrados } from "./contexto/comparativa-mensual";
import { MercadoStrip } from "./contexto/mercado-strip";
import { SaludStrip, type OverviewConCobertura } from "./contexto/salud-strip";

/**
 * Contexto de mercado y salud competitiva — las dos tiras de `overview`.
 *
 * Una sola llamada alimenta las dos secciones, y por eso comparten módulo: el
 * `overview` del ámbito trae tanto las magnitudes de mercado como los
 * indicadores de competencia. Aquí queda la consulta, el recorte a meses
 * cerrados y el estado de error; lo que cada tira declara —y por qué se
 * abstiene cuando se abstiene— está en `contexto/mercado-strip.tsx` y
 * `contexto/salud-strip.tsx`, y la comparativa mensual, que es pura y tiene su
 * propio test, en `contexto/comparativa-mensual.ts`.
 *
 * La única cifra derivada en cliente es el badge de anomalía, y va etiquetado
 * como tal — la salida que el invariante 1 de `frontend-data-invariants.md`
 * permite («si un valor es estimado, etiquétalo»).
 */

// `CoberturaMetrica`, `celdaSalud` y `coberturaSinMedir` viven en
// `lib/cobertura.ts` desde el 2026-08-30. Estaban aquí, y por eso la regla que
// implementan —no afirmar un porcentaje cuyo denominador no se conoce— solo se
// aplicaba en esta pantalla: `/competidores` publicaba las mismas magnitudes
// sin acotarlas. Se reexportan, junto con la comparativa mensual, para no
// romper a quien las importaba de aquí.
export type { CeldaSalud, CoberturaMetrica };
export { celdaSalud, coberturaSinMedir };
export { compararMeses, mesesCerrados };
export type { ComparativaMensual, MesAgregado } from "./contexto/comparativa-mensual";

export function ContextoStrip() {
  const overview = useFilteredQuery<OverviewConCobertura>(
    ["analytics", "overview"],
    "/api/v1/analytics/overview",
    { staleTime: 5 * 60 * 1000 },
  );

  const data = overview.data;
  const loading = overview.isLoading;

  const comparativa = useMemo(() => {
    const mesActual = new Date().toISOString().slice(0, 7);
    return compararMeses(data?.por_mes, mesActual);
  }, [data?.por_mes]);

  // Nº de meses cerrados que sirven de historia al badge de anomalía (la serie
  // menos el mes que se está juzgando). `isAnomaly` ya se abstiene con menos de
  // tres, así que aquí sólo hace falta para redactar su tooltip.
  const historial = useMemo(() => {
    const mesActual = new Date().toISOString().slice(0, 7);
    return Math.max(0, mesesCerrados(data?.por_mes, mesActual).length - 1);
  }, [data?.por_mes]);

  if (overview.error) {
    return (
      <section aria-labelledby="resumen-contexto" className="mb-5.5">
        <h2 id="resumen-contexto" className="mb-2.5 text-xs font-semibold">
          Contexto de mercado
        </h2>
        <PanelError
          title="No se pudo cargar el contexto"
          detail={(overview.error as Error).message}
          onRetry={() => void overview.refetch()}
        />
      </section>
    );
  }

  return (
    <>
      <MercadoStrip
        data={data}
        loading={loading}
        comparativa={comparativa}
        historial={historial}
      />
      <SaludStrip data={data} loading={loading} />
    </>
  );
}
