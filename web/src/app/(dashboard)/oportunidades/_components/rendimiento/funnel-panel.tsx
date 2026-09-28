"use client";

/**
 * El embudo: identificadas, presentadas y ganadas, con la tasa de conversión
 * de cada salto.
 *
 * Los tres conteos vienen de `GET /pursuits/metrics` sobre el periodo elegido;
 * las barras son proporcionales a esos totales y nada más. La unidad es la
 * **oportunidad**, no el expediente: desde la revisión `v110` un expediente
 * partido en lotes puede tener una por lote, y el propio contrato lo declara
 * (`unidad_de_conteo`), así que la pantalla no tiene que suponerlo.
 */
import { Panel, PanelEmpty, PanelLoading, PanelTitle } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import type { PursuitMetrics } from "@/hooks/use-pursuits";
import { cn, formatNumber } from "@/lib/utils";

const ETAPAS = [
  { key: "pursuits_identified", label: "Identificadas", sobre: null },
  {
    key: "pursuits_submitted",
    label: "Presentadas",
    sobre: { key: "pursuits_identified", nombre: "identificadas" },
  },
  {
    key: "pursuits_won",
    label: "Ganadas",
    sobre: { key: "pursuits_submitted", nombre: "presentadas" },
  },
] as const;

/**
 * La conversión de una etapa sobre la anterior.
 *
 * Es el único cociente que esta pantalla calcula, y no contradice ADR-014: los
 * dos números están en el mismo payload, cuentan la misma unidad y hablan del
 * mismo periodo, así que no se inventa ninguna base de cálculo. Sin denominador
 * —cero identificadas— no hay tasa que enseñar, y se calla en vez de escribir
 * «0 %».
 */
export function conversion(numerador: number, denominador: number): string | null {
  if (denominador <= 0) return null;
  return `${Math.round((numerador / denominador) * 100)} %`;
}

export function FunnelPanel({
  metrics,
  cargando,
  onAbrirRadar,
}: {
  metrics: PursuitMetrics | undefined;
  cargando: boolean;
  onAbrirRadar: () => void;
}) {
  const max = Math.max(1, metrics?.pursuits_identified ?? 0);

  return (
    <Panel>
      <PanelTitle title="Embudo de oportunidades" hint="Cuenta oportunidades, no expedientes" />
      {cargando ? (
        <PanelLoading height={180} />
      ) : !metrics || metrics.pursuits_identified === 0 ? (
        <PanelEmpty
          title="Todavía no hay oportunidades"
          hint="El embudo se llena al convertir señales del Radar en oportunidades."
          action={
            <Button type="button" variant="outline" size="sm" onClick={onAbrirRadar}>
              Abrir el Radar
            </Button>
          }
        />
      ) : (
        <div className="space-y-2.5 py-1">
          {ETAPAS.map((etapa, index) => {
            const valor = metrics[etapa.key];
            const tasa = etapa.sobre ? conversion(valor, metrics[etapa.sobre.key]) : null;
            return (
              <div key={etapa.key} className="grid grid-cols-[128px_1fr_64px] items-center gap-3">
                <div className="min-w-0">
                  <span className="text-tf-meta text-muted-foreground">{etapa.label}</span>
                  {tasa && etapa.sobre ? (
                    // La tasa va pegada a su etapa y no en una tarjeta aparte:
                    // sin el nombre del denominador al lado, un «58 %» suelto
                    // no dice sobre qué se mide.
                    <span className="block truncate text-tf-micro text-muted-foreground">
                      {tasa} de las {etapa.sobre.nombre}
                    </span>
                  ) : null}
                </div>
                <div className="h-6 overflow-hidden rounded-md bg-secondary/60">
                  {/* Sin transición: al cambiar de periodo la barra se pinta ya
                      en su valor (docs/frontend-motion.md, «Qué NO animar»). */}
                  <div
                    className={cn(
                      "h-full rounded-md",
                      index === 0 && "bg-primary/30",
                      index === 1 && "bg-primary/60",
                      index === 2 && "bg-primary",
                    )}
                    style={{ width: `${Math.max(valor > 0 ? 2 : 0, (valor / max) * 100)}%` }}
                  />
                </div>
                <span className="tf-tnum text-right text-tf-meta font-semibold">
                  {formatNumber(valor)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
