"use client";

/**
 * La franja de la agenda: cinco contadores que **además filtran**, y el aviso
 * de recorte.
 *
 * Antes eran cuatro celdas de estadística —las mismas que «Tu día» del
 * Resumen— que ocupaban la mejor fila de la pantalla y no hacían nada al
 * pulsarlas. Como botones dicen lo mismo en la mitad de alto y contestan a la
 * pregunta siguiente («¿cuáles son esas siete?») sin salir de la lista.
 *
 * El número de cada uno lo calcula la API sobre el ámbito pedido y **es el
 * recuento de filas que lo llevan** en `cuenta_en`: pulsar «Sin próxima
 * acción · 2» deja exactamente esas dos. Cada contador mide un reloj distinto
 * —el plazo externo, la acción interna, la decisión sin tomar, la oportunidad
 * sin siguiente paso y la que hay que cerrar—, así que van separados y no en un
 * total (ver `PipelineAgendaContadores`).
 *
 * El aviso existe porque unos contadores que describen una lista recortada no
 * son totales, y decirlo es la mitad del invariante (ADR-014).
 */

import type { ReactNode } from "react";
import { cn, formatCompactCurrency, formatNumber } from "@/lib/utils";
import { Aviso } from "@/components/console/panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { PipelineAgenda } from "@/hooks/use-pursuits";
import type { Agenda } from "../../_hooks/use-agenda";
import { CONTADORES } from "./agenda-meta";

const TONO = { destructive: "text-destructive", warning: "text-warning" } as const;

/** Qué se quedó fuera de la lista, en el orden en que la API la recorta. */
function recortes(data: PipelineAgenda): string[] {
  const partes: string[] = [];
  if (data.pursuits_truncados) partes.push("hay más oportunidades que las listadas");
  if (data.tareas_truncadas) partes.push("hay más tareas que las listadas");
  if (data.senales_truncadas) partes.push("hay más señales que las listadas");
  return partes;
}

export function AgendaContadores({
  agenda,
  children,
}: {
  agenda: Agenda;
  /** Lo que va a la derecha de la franja (la suscripción al calendario). */
  children?: ReactNode;
}) {
  const { data, isLoading, filtro } = agenda;
  const contadores = data?.contadores;
  const recortada = data ? recortes(data) : [];

  return (
    <>
      {/* Dos columnas en móvil —los cinco contadores y el calendario hacen seis
          celdas justas— y una fila desde `md`. Una tira con scroll horizontal
          habría escondido tres de los cinco números, que es lo que hay que ver. */}
      <div className="grid flex-none grid-cols-2 gap-1.5 md:flex md:flex-wrap md:items-center">
        {isLoading ? (
          Array.from({ length: CONTADORES.length }, (_, index) => (
            <Skeleton key={index} className="h-8 rounded-md md:h-7 md:w-40" />
          ))
        ) : contadores ? (
          <div role="group" aria-label="Filtrar compromisos" className="contents">
            {CONTADORES.map((contador) => {
              const n = contadores[contador.key];
              const on = filtro === contador.key;
              const importe =
                contador.key === "plazo_semana" && n > 0
                  ? formatCompactCurrency(contadores.plazo_semana_importe_eur)
                  : null;
              return (
                <button
                  key={contador.key}
                  type="button"
                  aria-pressed={on}
                  // A cero no hay filas que enseñar; encendido sí se puede
                  // apagar aunque su número haya bajado a cero mientras tanto.
                  disabled={n === 0 && !on}
                  onClick={() => agenda.alternarFiltro(contador.key)}
                  className={cn(
                    // 32 px de alto en móvil: se pulsa con el pulgar.
                    "tf-pressable inline-flex min-h-8 min-w-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-left text-tf-meta font-medium md:min-h-7 md:flex-none",
                    on
                      ? "border-primary/30 bg-primary/10 text-primary"
                      : "border-border/70 text-muted-foreground hover:text-foreground",
                    "disabled:pointer-events-none disabled:opacity-70",
                  )}
                >
                  {/* El rótulo delante y la cifra detrás, como en las pestañas:
                      «5 Plazo pasado» se leía como una frase mal concordada. */}
                  <span className="min-w-0 flex-1 leading-tight md:flex-none">{contador.label}</span>
                  <span
                    className={cn(
                      "tf-tnum flex-none text-tf-body font-semibold",
                      !on && n > 0 && (contador.tono ? TONO[contador.tono] : "text-foreground"),
                    )}
                  >
                    {formatNumber(n)}
                  </span>
                  {importe && <span className="flex-none font-normal">· {importe}</span>}
                </button>
              );
            })}
          </div>
        ) : null}
        {children && <div className="flex md:ml-auto md:flex-none [&>*]:flex-1">{children}</div>}
      </div>

      {recortada.length > 0 && (
        <Aviso tone="warning" className="flex-none">
          Agenda parcial: {recortada.join(", ")}. Los contadores cuentan solo lo listado.
        </Aviso>
      )}
    </>
  );
}
