"use client";

/**
 * Las dos fechas de una oportunidad, separadas y etiquetadas por **quién manda
 * en ellas**.
 *
 * El plazo de presentación lo fija el órgano de contratación y no se negocia;
 * la próxima acción se la pone el equipo y se mueve cuando quiera. Durante meses
 * viajaron fusionadas en un solo `due_date` —el mínimo de las dos— y la fila no
 * decía cuál de las dos vencía: la gente corría por una fecha propia creyendo
 * que era la del pliego, o dejaba pasar la del pliego creyendo que era suya.
 * Ahora el backend manda las dos por separado y esta caja las presenta como lo
 * que son: una externa y una interna.
 */

import { EMPTY, formatDate } from "@/lib/utils";
import { SectionTitle } from "@/components/console/panel";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";
import { NextActionEditor } from "./next-action-editor";

function Fecha({
  label,
  duenno,
  valor,
  detalle,
}: {
  label: string;
  duenno: "externo" | "interna";
  valor: string | null | undefined;
  detalle?: string | null;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 py-0.5">
      <dt className="flex flex-none items-center gap-1.5 text-muted-foreground">
        {label}
        <span className="rounded-sm border border-border/70 bg-muted/60 px-1 font-mono text-[8.5px] font-semibold uppercase tracking-[0.06em]">
          {duenno}
        </span>
      </dt>
      <dd className="min-w-0 text-right">
        <span className="tf-tnum">{valor ? formatDate(valor) : EMPTY}</span>
        {detalle && <span className="block truncate text-[10px] text-muted-foreground">{detalle}</span>}
      </dd>
    </div>
  );
}

export function AgendaFechas({ item, enfoque }: { item: PipelineAgendaItem; enfoque: number }) {
  const esTarea = item.kind === "tarea";
  // En una fila de tarea el `due_date` es el de **esa** tarea; el plazo de
  // presentación no viaja en ella (lo trae la fila de la oportunidad).
  const presentacion = esTarea ? null : item.due_date;
  const accion = esTarea ? item.due_date : item.next_action_due;
  const textoAccion = esTarea ? (item.tarea_texto ?? item.next_action) : item.next_action;

  return (
    <div>
      <SectionTitle>Fechas</SectionTitle>
      <dl className="mb-2 space-y-0.5 text-[11.5px]">
        <Fecha label="Presentación" duenno="externo" valor={presentacion} />
        <Fecha label="Próxima acción" duenno="interna" valor={accion} detalle={textoAccion} />
      </dl>
      {esTarea && (
        <p className="mb-2 text-[10px] text-muted-foreground">
          El plazo de presentación va en la fila de la oportunidad, no en la de la tarea.
        </p>
      )}
      {item.pursuit_id != null && item.version != null && (
        <NextActionEditor item={item} enfoque={enfoque} />
      )}
    </div>
  );
}
