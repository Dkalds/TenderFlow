"use client";

/**
 * F4.1 — valor ponderado del pipeline y previsión por trimestre.
 *
 * La cifra y el reparto los calcula la API; aquí se pintan **con sus
 * supuestos**: las probabilidades por etapa que usó y cuántas oportunidades
 * quedaron fuera por no tener importe publicado. Sin eso el número no se
 * puede reproducir, y es un número que se lleva a comité.
 */
import { Panel, PanelTitle } from "@/components/console/panel";
import { PrevisionTrimestral, SupuestosEtapas } from "@/components/pursuits/prevision-trimestral";
import type { PursuitMetrics } from "@/hooks/use-pursuits";
import { previsionOrdenada, supuestosEtapas } from "@/lib/pipeline-ponderado";
import { formatCompactCurrency, formatNumber } from "@/lib/utils";

export function ValorPonderado({ metrics }: { metrics: PursuitMetrics }) {
  return (
    <Panel>
      <PanelTitle
        title="Valor ponderado del pipeline"
        hint="Oportunidades abiertas en la ventana"
      />
      <p className="tf-tnum text-tf-title leading-none font-semibold">
        {formatCompactCurrency(metrics.pipeline_value_eur)}
      </p>
      <p className="mt-1.5 text-tf-micro leading-normal text-muted-foreground">
        Importe de cada oportunidad abierta por la probabilidad de su etapa. Es un supuesto, no
        una previsión de cobro.
        {metrics.pipeline_sin_importe > 0
          ? ` ${formatNumber(metrics.pipeline_sin_importe)} sin importe publicado no cuentan.`
          : null}
      </p>
      <SupuestosEtapas className="mt-3" supuestos={supuestosEtapas(metrics)} />
      <PrevisionTrimestral prevision={previsionOrdenada(metrics)} />
    </Panel>
  );
}
