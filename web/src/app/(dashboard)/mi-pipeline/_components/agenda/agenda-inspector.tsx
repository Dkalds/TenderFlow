"use client";

/**
 * Inspector en el mismo plano: el detalle del compromiso seleccionado.
 *
 * Cada clase de compromiso enseña lo suyo, porque lo que hace falta para
 * decidir es distinto: una oportunidad o una tarea piden sus dos fechas y la
 * lista de tareas; un contrato, su fin efectivo con el origen y la ventana de
 * relicitación; una señal, la regla que la trajo. La cabecera y los datos
 * comunes son los mismos para las cinco.
 *
 * Decisión escrita: el inspector no baja de `xl`. Lo accionable de cada
 * compromiso ya está en su ficha (abrir / completar / preparar renovación /
 * seguir / descartar), así que en móvil no se pierde ninguna decisión. Lo que
 * sí queda fuera es el editor de próxima acción y el alta de tareas: escribir
 * texto libre y una fecha en 375 px pide una hoja a pantalla completa, no un
 * panel lateral encogido, y eso es trabajo aparte — anotado como pendiente, no
 * resuelto con un `hidden`.
 */

import type { ReactNode } from "react";
import { ExternalLink } from "lucide-react";
import { cn, EMPTY, formatCompactCurrency, formatDate, truncate } from "@/lib/utils";
import { statusLabel } from "@/components/pursuits/pursuit-presenters";
import { PanelEmpty, ROTULO_DATO } from "@/components/console/panel";
import { Button, buttonVariants } from "@/components/ui/button";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import type { Agenda } from "../../_hooks/use-agenda";
import { AgendaContrato } from "./agenda-contrato";
import { AgendaFechas } from "./agenda-fechas";
import { AgendaSenal } from "./agenda-senal";
import { AgendaTareas } from "./agenda-tareas";
import { CHIP_POR_BANDA, claveDe, etiquetaKind, plazoChip, tipoDeFecha, tituloDe } from "./agenda-meta";

function Dato({ label, valor }: { label: string; valor: ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="flex-none text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-right">{valor}</dd>
    </div>
  );
}

function Cabecera({ item }: { item: PipelineAgendaItem }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5">
        <span
          className={cn(
            "tf-tnum inline-flex h-5 items-center rounded-full px-2 text-tf-micro font-semibold",
            CHIP_POR_BANDA[item.urgencia],
          )}
        >
          {plazoChip(item)}
        </span>
        <span className={ROTULO_DATO}>{etiquetaKind(item)}</span>
      </div>
      <h3 className="text-tf-body font-semibold">{tituloDe(item)}</h3>
      <p className="mt-1 text-tf-micro text-muted-foreground">
        {tipoDeFecha(item)}
        {item.due_date ? ` · ${formatDate(item.due_date)}` : " · sin fecha"}
      </p>
    </div>
  );
}

export function AgendaInspector({ agenda }: { agenda: Agenda }) {
  const item = agenda.active;
  const esPursuitOTarea = item?.kind === "pursuit" || item?.kind === "tarea";

  return (
    <aside
      aria-label="Detalle del compromiso"
      className="hidden min-w-0 self-start rounded-xl border border-border/60 bg-card p-4 xl:sticky xl:top-0 xl:block"
    >
      {!item ? (
        <PanelEmpty size="sm" hint="Selecciona un compromiso para ver su detalle." />
      ) : (
        <div className="space-y-4">
          <Cabecera item={item} />

          <dl className="space-y-1.5 text-tf-meta">
            {item.organo && <Dato label="Órgano" valor={truncate(item.organo, 40)} />}
            <Dato
              label="Importe"
              valor={
                <span className="tf-tnum">
                  {item.importe_eur != null ? formatCompactCurrency(item.importe_eur) : EMPTY}
                </span>
              }
            />
            {item.ccaa && <Dato label="CCAA" valor={item.ccaa} />}
            {item.status && <Dato label="Estado" valor={statusLabel(item.status)} />}
            {item.responsible_name && <Dato label="Responsable" valor={item.responsible_name} />}
            {item.kind === "renovacion" && item.adjudicatario && (
              <Dato label="Adjudicatario" valor={truncate(item.adjudicatario, 36)} />
            )}
            {item.kind === "renovacion" && item.riesgo_cambio != null && (
              <Dato
                label="Riesgo de cambio"
                valor={
                  <span className="tf-tnum">
                    {Math.round(item.riesgo_cambio * 100)}%
                  </span>
                }
              />
            )}
          </dl>

          {/* `key` por fila y versión: cambiar de compromiso remonta el editor
              con el valor del servidor, sin efectos que sincronicen estado. */}
          {esPursuitOTarea && (
            <AgendaFechas
              key={`${claveDe(item)}:${item.version ?? 0}`}
              item={item}
              enfoque={agenda.focoAccion}
            />
          )}
          {esPursuitOTarea && item.pursuit_id != null && (
            <AgendaTareas pursuitId={item.pursuit_id} />
          )}
          {item.kind === "contrato" && <AgendaContrato item={item} />}
          {item.kind === "senal" && (
            <AgendaSenal
              item={item}
              onSeguir={() => void agenda.seguir(item)}
              onDescartar={() => agenda.descartar(item)}
              onPosponer={() => agenda.posponer(item)}
            />
          )}

          <div className="flex flex-wrap gap-1.5 border-t border-border/50 pt-3">
            {item.kind !== "senal" && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => agenda.abrir(item)}
                className="flex-1 border-primary/30 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary"
              >
                {item.kind === "renovacion" ? "Anticipar oportunidad" : "Abrir ficha"}
              </Button>
            )}
            {item.url && (
              // Enlace a la página del expediente en PLACSP, nunca al documento:
              // los enlaces directos a pliegos llevan tokens rotativos y caducan.
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className={buttonVariants({
                  variant: "outline",
                  size: "sm",
                  className: "text-muted-foreground hover:text-foreground",
                })}
              >
                PLACSP
                <ExternalLink aria-hidden="true" />
              </a>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
