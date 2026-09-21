"use client";

/**
 * El embudo: identificadas → presentadas → ganadas, con la tasa de conversión
 * de cada salto.
 *
 * Los tres conteos vienen de `GET /pursuits/metrics` sobre el periodo elegido;
 * las barras son proporcionales a esos totales y nada más. La unidad es la
 * **oportunidad**, no el expediente: desde la revisión `v110` un expediente
 * partido en lotes puede tener una por lote, y el propio contrato lo declara
 * (`unidad_de_conteo`), así que la pantalla no tiene que suponerlo.
 */
import { EmptyState } from "@/components/ui/empty-state";
import { Trophy } from "lucide-react";
import { Panel, PanelLoading, PanelTitle } from "@/components/console/panel";
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
 * mismo periodo, así que no se inventa ningún denominador. Sin denominador
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
      <PanelTitle title="Funnel de pursuits" hint="Oportunidades, no expedientes" />
      {cargando ? (
        <PanelLoading height={180} />
      ) : !metrics || metrics.pursuits_identified === 0 ? (
        <EmptyState
          icon={Trophy}
          title="Todavía no hay pursuits"
          hint="El embudo se llena siguiendo señales desde el Radar o desde la agenda."
          actionLabel="Abrir el Radar"
          onAction={onAbrirRadar}
        />
      ) : (
        <div className="space-y-2.5 py-1">
          {ETAPAS.map((etapa, index) => {
            const valor = metrics[etapa.key];
            const tasa = etapa.sobre ? conversion(valor, metrics[etapa.sobre.key]) : null;
            return (
              <div key={etapa.key} className="grid grid-cols-[128px_1fr_64px] items-center gap-3">
                <div className="min-w-0">
                  <span className="text-[11.5px] text-muted-foreground">{etapa.label}</span>
                  {tasa && etapa.sobre ? (
                    // La tasa va pegada a su etapa y no en una tarjeta aparte:
                    // sin el nombre del denominador al lado, un «58 %» suelto
                    // no dice sobre qué se mide.
                    <span className="block truncate text-[10px] leading-[1.3] text-muted-foreground">
                      {tasa} de las {etapa.sobre.nombre}
                    </span>
                  ) : null}
                </div>
                <div className="h-6 overflow-hidden rounded-md bg-secondary/60">
                  <div
                    className={cn(
                      "h-full rounded-md transition-[width] duration-300 ease-out",
                      index === 0 && "bg-primary/25",
                      index === 1 && "bg-primary/55",
                      index === 2 && "bg-primary",
                    )}
                    style={{ width: `${Math.max(valor > 0 ? 2 : 0, (valor / max) * 100)}%` }}
                  />
                </div>
                <span className="tf-tnum text-right font-mono text-[12px] font-semibold">
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
