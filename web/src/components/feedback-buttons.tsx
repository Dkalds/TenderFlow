"use client";

import * as React from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { registrarEvento } from "@/lib/analytics";
import { apiMutate } from "@/lib/api-client";

/**
 * Pulgares de calidad sobre una respuesta completa del asistente.
 *
 * Módulo propio y no dentro de `chat-thread.tsx`: la ficha del pliego
 * (`pursuits/tender-fact-sheet.tsx`) solo necesita los pulgares, y
 * importarlos de allí le metía en el First Load el hilo de chat entero con
 * react-markdown y remark-gfm.
 *
 * Hasta C5.4 el voto era **solo** un evento de telemetría: no llegaba a ninguna
 * tabla, así que se le pedía al usuario que evaluase y su evaluación se tiraba.
 * Ahora también va a `POST /feedback/asistente`, que guarda el **hash** de la
 * pregunta —no su texto— junto al modo y al voto.
 *
 * `pregunta` viaja para poder hashearla en servidor con la sal de la
 * aplicación; hashearla aquí dejaría la sal en el navegador, que es lo mismo
 * que no tenerla. Sin `pregunta` (resumen, ficha) se manda la etiqueta del modo:
 * el turno no tiene pregunta de usuario, y el hash agrupa igual.
 *
 * El fallo de red se ignora a propósito: quien vota nos hace un favor, y un
 * error en su pantalla por nuestra tabla convierte esa cortesía en un problema.
 */
export function FeedbackButtons({
  modo,
  pregunta,
  licitacionId,
}: {
  modo: "pregunta" | "resumen" | "ficha";
  pregunta?: string;
  licitacionId?: string;
}) {
  const [voted, setVoted] = React.useState<"si" | "no" | null>(null);

  const vote = (util: "si" | "no") => {
    if (voted) return;
    setVoted(util);
    registrarEvento("asistente_feedback", { modo, util });
    void apiMutate("POST", "/api/v1/feedback/asistente", {
      pregunta: pregunta?.trim() || `[${modo}]`,
      modo,
      voto: util,
      licitacion_id: licitacionId,
    }).catch(() => {
      /* el voto ya está reflejado en la UI; un fallo aquí no es del usuario */
    });
  };

  return (
    <div className="mt-1.5 flex items-center gap-1" role="group" aria-label="¿Te ha servido?">
      {voted ? (
        <span className="text-muted-foreground text-[11px]">Gracias por el feedback.</span>
      ) : (
        <>
          <button
            type="button"
            onClick={() => vote("si")}
            aria-label="Respuesta útil"
            className="text-muted-foreground hover:text-foreground grid h-6 w-6 place-items-center rounded-md transition-colors"
          >
            <ThumbsUp className="h-3 w-3" aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() => vote("no")}
            aria-label="Respuesta no útil"
            className="text-muted-foreground hover:text-foreground grid h-6 w-6 place-items-center rounded-md transition-colors"
          >
            <ThumbsDown className="h-3 w-3" aria-hidden="true" />
          </button>
        </>
      )}
    </div>
  );
}
