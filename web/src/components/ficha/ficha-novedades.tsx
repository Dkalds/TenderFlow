"use client";

/**
 * «Ha cambiado desde tu última visita»: la franja de arriba de la ficha.
 *
 * Abrir la ficha registra la visita (`POST /licitaciones/{id}/visita`) y la
 * respuesta dice qué cambió desde la anterior: plazo, importe, estado,
 * documentos nuevos y recursos. La primera vez no hay con qué comparar, y sin
 * cambios tampoco hay franja: aquí solo se pinta lo que hay que leer.
 */

import { Panel } from "@/components/console/panel";
import { useVisitaFicha } from "@/hooks/use-licitacion";
import { formatDateTime, formatRelativeTime } from "@/lib/utils";

export function FichaNovedades({ licitacionId }: { licitacionId: string }) {
  const visita = useVisitaFicha(licitacionId);
  const items = visita?.items ?? [];
  if (!visita?.desde || items.length === 0) return null;

  return (
    <Panel tono="accent" role="region" aria-label="Cambios desde tu última visita">
      <p className="text-tf-meta font-medium">
        Ha cambiado desde tu última visita{" "}
        <time dateTime={visita.desde} className="text-muted-foreground font-normal">
          ({formatDateTime(visita.desde)})
        </time>
      </p>
      <ul className="mt-1.5 space-y-1">
        {items.map((item, i) => (
          <li key={`${item.subtipo}-${item.cuando}-${i}`} className="text-tf-meta leading-relaxed">
            <span className="font-medium">{item.titulo}</span>
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
