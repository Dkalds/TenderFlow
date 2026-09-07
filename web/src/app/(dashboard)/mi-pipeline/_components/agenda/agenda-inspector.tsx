"use client";

/**
 * Inspector en el mismo plano: el detalle del compromiso seleccionado y, para
 * pursuits, el editor de próxima acción.
 */

import { ExternalLink } from "lucide-react";
import { cn, EMPTY, formatCompactCurrency, formatDate, truncate } from "@/lib/utils";
import { FechaFinOrigenBadge } from "@/components/pursuits/fecha-fin-origen-badge";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import { CHIP_POR_BANDA, KIND_META, plazoChip, STATUS_LABELS } from "./agenda-meta";
import { NextActionEditor } from "./next-action-editor";

export function AgendaInspector({
  item,
  onSeguir,
  onDescartar,
  onAbrir,
}: {
  item: PipelineAgendaItem | undefined;
  onSeguir: (item: PipelineAgendaItem) => Promise<void>;
  onDescartar: (item: PipelineAgendaItem) => void;
  onAbrir: (item: PipelineAgendaItem) => void;
}) {
  const esPursuit = item?.kind === "pursuit" && item.pursuit_id != null;

  return (
    // Decisión escrita: el inspector no baja de `xl`. Lo accionable de cada
    // compromiso ya está en su ficha (abrir / seguir / anticipar / descartar),
    // así que en móvil no se pierde ninguna decisión. Lo que sí queda fuera es
    // el editor de próxima acción: escribir un texto libre y una fecha en 375 px
    // pide una hoja a pantalla completa, no un panel lateral encogido, y eso es
    // trabajo aparte — anotado como pendiente, no resuelto con un `hidden`.
    <aside className="hidden min-w-0 self-start rounded-xl border border-border/60 bg-card/70 p-4 xl:sticky xl:top-0 xl:block">
      {!item ? (
        <p className="py-8 text-center text-[11.5px] text-muted-foreground">
          Selecciona un compromiso para ver su detalle.
        </p>
      ) : (
        <div className="space-y-4">
          <div>
            <div className="mb-1.5 flex items-center gap-1.5">
              <span
                className={cn(
                  "inline-flex h-5 items-center rounded-full px-2 font-mono text-[10px] font-semibold",
                  CHIP_POR_BANDA[item.urgencia],
                )}
              >
                {plazoChip(item)}
              </span>
              <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                {KIND_META[item.kind].label}
              </span>
            </div>
            <h3 className="text-[13px] font-semibold leading-[1.4]">
              {item.titulo ?? item.licitacion_id}
            </h3>
            {item.due_date && (
              <p className="mt-1 text-[11px] text-muted-foreground">
                Vence el {formatDate(item.due_date)}
              </p>
            )}
          </div>

          <dl className="space-y-1.5 text-[11.5px]">
            {item.organo && (
              <div className="flex justify-between gap-3">
                <dt className="flex-none text-muted-foreground">Órgano</dt>
                <dd className="truncate text-right">{truncate(item.organo, 40)}</dd>
              </div>
            )}
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Importe</dt>
              <dd className="tf-tnum font-mono">
                {item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
              </dd>
            </div>
            {item.ccaa && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">CCAA</dt>
                <dd>{item.ccaa}</dd>
              </div>
            )}
            {item.kind === "pursuit" && item.status && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Estado</dt>
                <dd>{STATUS_LABELS[item.status] ?? item.status}</dd>
              </div>
            )}
            {item.kind === "pursuit" && item.responsible_name && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Responsable</dt>
                <dd className="truncate">{item.responsible_name}</dd>
              </div>
            )}
            {item.kind === "senal" && item.rule_nombre && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Regla</dt>
                <dd className="truncate">{item.rule_nombre}</dd>
              </div>
            )}
            {item.kind === "renovacion" && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Vencimiento</dt>
                {/* El 94% de estas fechas se calcula con la duración del
                    contrato; presentarlas como publicadas era prometer una
                    precisión que la fuente no da. */}
                <dd className="flex items-center gap-1.5">
                  {formatDate(item.due_date)}
                  <FechaFinOrigenBadge origen={item.fecha_fin_origen} />
                </dd>
              </div>
            )}
            {item.kind === "renovacion" && item.adjudicatario && (
              <div className="flex justify-between gap-3">
                <dt className="flex-none text-muted-foreground">Adjudicatario</dt>
                <dd className="truncate text-right">{truncate(item.adjudicatario, 36)}</dd>
              </div>
            )}
            {item.kind === "renovacion" && item.riesgo_cambio != null && (
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Riesgo de cambio</dt>
                <dd className="tf-tnum font-mono">{Math.round(item.riesgo_cambio * 100)}%</dd>
              </div>
            )}
          </dl>

          {esPursuit && (
            <NextActionEditor key={`${item.licitacion_id}:${item.version ?? 0}`} item={item} />
          )}

          <div className="flex flex-wrap gap-1.5 border-t border-border/50 pt-3">
            {item.kind === "pursuit" ? (
              <button
                type="button"
                onClick={() => onAbrir(item)}
                className="tf-pressable h-7 flex-1 rounded-md border border-primary/30 bg-primary/10 px-2.5 text-[11.5px] font-medium text-primary"
              >
                Abrir ficha
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => void onSeguir(item)}
                  className="tf-pressable h-7 flex-1 rounded-md border border-primary/30 bg-primary/10 px-2.5 text-[11.5px] font-medium text-primary"
                >
                  {item.kind === "renovacion" ? "Anticipar pursuit" : "Seguir"}
                </button>
                {item.kind === "senal" && (
                  <button
                    type="button"
                    onClick={() => onDescartar(item)}
                    className="tf-pressable h-7 rounded-md border border-border/70 px-2.5 text-[11.5px] font-medium text-muted-foreground hover:text-destructive"
                  >
                    Descartar
                  </button>
                )}
              </>
            )}
            {item.url && (
              // Enlace a la página del expediente en PLACSP, nunca al documento:
              // los enlaces directos a pliegos llevan tokens rotativos y caducan.
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="tf-pressable inline-flex h-7 items-center gap-1 rounded-md border border-border/70 px-2.5 text-[11.5px] font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                PLACSP
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
