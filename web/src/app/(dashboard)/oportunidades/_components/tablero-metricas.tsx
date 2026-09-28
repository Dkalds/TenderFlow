"use client";

import { StatCell } from "@/components/console/panel";
import { formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { PursuitMetrics } from "@/hooks/use-pursuits";

/**
 * La tira del tablero.
 *
 * La versión anterior enseñaba el embudo **acumulado** de la organización
 * —toda oportunidad creada alguna vez, toda la que llegó a presentarse— encima
 * de unos carriles que contaban el **estado actual**. Las dos cifras eran
 * correctas y no cuadraban entre sí, así que cada una llevaba debajo un matiz
 * explicando por qué no había que compararlas con lo de abajo.
 *
 * Esto cuenta lo mismo que el tablero: lo que hay abierto ahora. `/pursuits/metrics`
 * ya devolvía `pipeline_value_eur`, `pipeline_sin_importe` y
 * `prevision_trimestral` y la pantalla no los pintaba.
 *
 * `pipeline_sin_importe` va en ámbar porque no es una cifra de negocio, es un
 * hueco de dato: esas oportunidades quedan fuera de las dos primeras columnas y
 * quien mira la tira tiene que saber cuánto le falta para fiarse de ellas.
 *
 * Las celdas son `StatCell`, el KPI canónico; la tira va de borde a borde bajo
 * la cabecera, por eso no es un `StatStrip` (que lleva marco y radio).
 *
 * Esto es **el resumen**, no el informe: cuatro cifras sobre el tablero que se
 * está mirando. La vista completa de `GET /pursuits/metrics` —funnel con sus
 * tasas de conversión, valor ponderado con supuestos, pérdidas por motivo,
 * calidad del Radar y selector de periodo— es Oportunidades › **Rendimiento**
 * (`_components/rendimiento-view.tsx`). Si hace falta una cifra más aquí, casi
 * siempre lo que hace falta es abrir aquélla.
 */
export function TableroMetricas({
  metrics,
  cargando,
}: {
  metrics: PursuitMetrics | undefined;
  cargando: boolean;
}) {
  const trimestre = metrics?.prevision_trimestral ?? {};
  const claves = Object.keys(trimestre).sort();
  const actual = claves.length ? trimestre[claves[claves.length - 1]] : null;

  return (
    <section
      aria-label="Pipeline de la organización"
      className="border-border/70 bg-border/60 grid flex-none grid-cols-2 gap-px border-b lg:grid-cols-4"
    >
      <StatCell
        label="Valor del pipeline"
        hint="Oferta prevista de lo que sigue abierto"
        value={metrics ? formatCompactCurrency(metrics.pipeline_value_eur) : "—"}
        loading={cargando}
      />
      <StatCell
        label="Previsión del trimestre"
        hint="Estimación ponderada por fase"
        value={actual != null ? formatCompactCurrency(actual) : "—"}
        loading={cargando}
      />
      <StatCell
        label="Sin importe"
        hint="Quedan fuera de las dos cifras anteriores"
        value={metrics ? formatNumber(metrics.pipeline_sin_importe) : "—"}
        loading={cargando}
        tono="warning"
      />
      <StatCell
        label="Ganadas · adjudicado"
        hint="Acumulado histórico de la organización"
        value={
          metrics
            ? `${formatNumber(metrics.pursuits_won)} · ${formatCompactCurrency(metrics.awarded_amount_eur)}`
            : "—"
        }
        loading={cargando}
        tono="success"
      />
    </section>
  );
}
