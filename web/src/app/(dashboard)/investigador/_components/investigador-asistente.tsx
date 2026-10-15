"use client";

/**
 * La barra del asistente, encima de la lista de resultados: sobre qué
 * responderá y cómo abrirlo.
 *
 * Hasta 2026-10 aquí había un chat propio, en un panel junto a la lista. Hoy
 * la conversación es la del asistente único de la consola, que se abre a un
 * lado sin tapar la lista (no es modal, y esta pantalla le deja el hueco): se
 * siguen marcando resultados con él abierto, y la siguiente pregunta ya va
 * sobre lo marcado. Esta barra dice el alcance —todas las licitaciones o los
 * resultados marcados, hasta tres, que se quitan desde aquí— y ofrece la
 * pregunta obvia de cada caso.
 */

import { X } from "lucide-react";
import { Panel, ROTULO_DATO } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import type { ExpedienteMarcado } from "../_hooks/use-investigador";

interface Props {
  /** La consulta que se buscó: se ofrece responderla tal cual. */
  consulta: string;
  seleccion: ExpedienteMarcado[];
  onPreguntar: (pregunta: string, opciones?: { nueva?: boolean }) => void;
  onQuitar: (id: string) => void;
  /** Abre el asistente sobre el alcance de la barra, sin preguntar nada. */
  onAbrir: () => void;
}

export function InvestigadorAsistente({ consulta, seleccion, onPreguntar, onQuitar, onAbrir }: Props) {
  return (
    <Panel className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5">
      <h2 className="text-tf-body font-semibold">Asistente</h2>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
        <span className={ROTULO_DATO}>Sobre</span>
        {seleccion.length === 0 ? (
          <span className="text-tf-meta text-muted-foreground">todas las licitaciones</span>
        ) : (
          seleccion.map((s) => (
            <Button
              key={s.id}
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => onQuitar(s.id)}
              aria-label={`Quitar ${s.titulo} del asistente`}
              className="max-w-full"
            >
              <span className="max-w-56 truncate">{s.titulo}</span>
              <X aria-hidden="true" />
            </Button>
          ))
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {seleccion.length > 0 ? (
          <Button size="sm" onClick={onAbrir}>
            Preguntar por lo marcado
          </Button>
        ) : (
          <>
            {consulta && (
              <Button size="sm" variant="outline" onClick={() => onPreguntar(consulta, { nueva: true })}>
                <span className="max-w-64 truncate">Responder «{consulta}»</span>
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onAbrir}>
              Abrir el asistente
            </Button>
          </>
        )}
      </div>
    </Panel>
  );
}
