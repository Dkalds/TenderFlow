"use client";

/**
 * F4.1 — valor ponderado del pipeline y previsión por trimestre.
 *
 * La cifra y el reparto los calcula el backend; aquí se pintan **con sus
 * supuestos**: las probabilidades por etapa que usó y cuántas oportunidades
 * quedaron fuera por no tener importe publicado. Sin eso el número no se
 * puede reproducir, y es un número que se lleva a comité.
 */
import { Panel, PanelTitle } from "@/components/console/panel";
import type { PursuitMetrics } from "@/hooks/use-pursuits";
import { previsionOrdenada, supuestosEtapas } from "@/lib/pipeline-ponderado";
import { formatCompactCurrency, formatNumber } from "@/lib/utils";

export function ValorPonderado({ metrics }: { metrics: PursuitMetrics }) {
  const supuestos = supuestosEtapas(metrics);
  const prevision = previsionOrdenada(metrics);
  const maxTrimestre = Math.max(1, ...prevision.map((t) => t.valor));
  return (
    <Panel>
      <PanelTitle
        title="Valor ponderado del pipeline"
        hint="Oportunidades abiertas en la ventana"
      />
      <p className="tf-tnum font-mono text-[22px] leading-none font-semibold">
        {formatCompactCurrency(metrics.pipeline_value_eur)}
      </p>
      <p className="mt-1.5 text-[11px] leading-[1.5] text-muted-foreground">
        Importe de cada oportunidad abierta por la probabilidad de su etapa. Es un supuesto, no
        una previsión de cobro.
        {metrics.pipeline_sin_importe > 0
          ? ` ${formatNumber(metrics.pipeline_sin_importe)} sin importe publicado no cuentan.`
          : null}
      </p>
      {supuestos.length > 0 ? (
        <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
          {supuestos.map((s) => (
            <div key={s.etapa} className="flex gap-1">
              <dt className="text-muted-foreground">{s.etiqueta}</dt>
              <dd className="tf-tnum font-medium">{s.probabilidad} %</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <h4 className="mt-4 mb-2 font-mono text-[9.5px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
        Previsión por trimestre
      </h4>
      {prevision.length === 0 ? (
        <p className="text-[11.5px] text-muted-foreground">
          Sin oportunidades abiertas con importe y fecha para repartir.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {prevision.map((t) => (
            <li key={t.clave} className="grid grid-cols-[64px_1fr_72px] items-center gap-3">
              <span className="text-[11.5px] text-muted-foreground">{t.etiqueta}</span>
              <div className="h-4 overflow-hidden rounded bg-secondary/60" aria-hidden="true">
                {/* Barra en SVG: el ancho es un atributo, no un estilo inline (C2.8). */}
                <svg className="h-full w-full" preserveAspectRatio="none" viewBox="0 0 100 1">
                  <rect
                    className="fill-primary/60"
                    height="1"
                    width={Math.max(2, (t.valor / maxTrimestre) * 100)}
                  />
                </svg>
              </div>
              <span className="tf-tnum text-right font-mono text-[11.5px] font-semibold">
                {formatCompactCurrency(t.valor)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[10.5px] leading-[1.45] text-muted-foreground">
        El trimestre sale de la fecha prevista de adjudicación y, sin ella, de la fecha límite.
      </p>
    </Panel>
  );
}
