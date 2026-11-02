"use client";

/**
 * «Ha cambiado desde tu última visita»: la franja de arriba de la ficha.
 *
 * Abrir la ficha registra la visita (`POST /licitaciones/{id}/visita`) y la
 * respuesta dice qué cambió desde la anterior: plazo, importe, estado,
 * documentos nuevos y recursos. La primera vez no hay con qué comparar, y sin
 * cambios tampoco hay franja: aquí solo se pinta lo que hay que leer. Cada
 * cambio lleva a la sección de la ficha donde se ve.
 */

import * as React from "react";
import { Panel } from "@/components/console/panel";
import { useVisitaFicha } from "@/hooks/use-licitacion";
import type { NovedadesDeFicha } from "@/lib/api-types";
import { formatDateTime, formatRelativeTime } from "@/lib/utils";

/** Sección de la ficha donde se ve cada clase de cambio (`services/avisos.py`). */
function seccionDe(subtipo: string): string {
  if (subtipo === "documento_nuevo") return "#ficha-pliegos";
  if (subtipo === "recurso" || subtipo === "adjudicado") return "#ficha-historia";
  return "#ficha-expediente";
}

type Novedad = NonNullable<NovedadesDeFicha["items"]>[number];

export function FichaNovedades({ licitacionId }: { licitacionId: string }) {
  const id = React.useId();
  const visita = useVisitaFicha(licitacionId);
  const items: Novedad[] = visita?.items ?? [];
  if (!visita?.desde || items.length === 0) return null;

  return (
    <Panel tono="accent" role="region" aria-labelledby={id}>
      <h3 id={id} className="text-tf-meta font-semibold">
        Ha cambiado desde tu última visita{" "}
        <time dateTime={visita.desde} className="text-muted-foreground font-normal">
          ({formatDateTime(visita.desde)})
        </time>
      </h3>
      <ul className="mt-1.5 space-y-1">
        {items.map((item, i) => (
          <li key={`${item.subtipo}-${item.cuando}-${i}`} className="text-tf-meta leading-relaxed">
            <a href={seccionDe(item.subtipo)} className="hover:text-primary font-medium hover:underline">
              {item.titulo}
            </a>
            {item.detalle ? <span className="text-muted-foreground"> · {item.detalle}</span> : null}
            {item.cuando ? (
              <time dateTime={item.cuando} className="text-muted-foreground">
                {" "}
                · {formatRelativeTime(item.cuando)}
              </time>
            ) : null}
          </li>
        ))}
      </ul>
    </Panel>
  );
}
