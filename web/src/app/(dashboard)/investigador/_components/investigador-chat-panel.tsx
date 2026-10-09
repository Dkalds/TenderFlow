"use client";

/**
 * El asistente, junto a la lista de resultados.
 *
 * Tiene su propia caja de texto, debajo del hilo: la conversación crece hacia
 * abajo y la siguiente pregunta se escribe donde termina la última respuesta.
 * Antes solo había la caja de arriba, compartida con la búsqueda, y seguir una
 * conversación larga era subir hasta ella en cada turno.
 *
 * El alcance se ve encima de la caja: todas las licitaciones, o los resultados
 * marcados en la lista (hasta tres; el asistente lee entonces sus pliegos y
 * cita de dónde saca cada dato).
 */

import { useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { Panel, PanelTitle, ROTULO_DATO } from "@/components/console/panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatThread } from "@/components/chat-thread";
import type { UseChatResult } from "@/hooks/use-ask";
import type { ExpedienteMarcado } from "../_hooks/use-investigador";

interface Props {
  chat: UseChatResult;
  onPreguntar: (pregunta: string, opciones?: { nueva?: boolean }) => void;
  /** La consulta que se buscó: se ofrece preguntarla tal cual si aún no hay conversación. */
  consulta: string;
  seleccion: ExpedienteMarcado[];
  onQuitar: (id: string) => void;
}

export function InvestigadorChatPanel({ chat, onPreguntar, consulta, seleccion, onQuitar }: Props) {
  const [pregunta, setPregunta] = useState("");
  const hayConversacion = chat.messages.length > 0 || chat.loading || Boolean(chat.error);

  const enviar = (evento: FormEvent<HTMLFormElement>) => {
    evento.preventDefault();
    if (!pregunta.trim() || chat.loading) return;
    onPreguntar(pregunta);
    setPregunta("");
  };

  return (
    <Panel className="min-w-0">
      <PanelTitle
        as="h2"
        title="Asistente"
        actions={
          chat.messages.length > 0 && !chat.loading ? (
            <Button variant="ghost" size="sm" onClick={chat.reset}>
              Nueva conversación
            </Button>
          ) : undefined
        }
      />

      {hayConversacion ? (
        <ChatThread messages={chat.messages} streaming={chat.streaming} loading={chat.loading} error={chat.error} />
      ) : (
        <div className="space-y-2">
          <p className="text-tf-meta text-muted-foreground">
            Pregunta por lo que has buscado, o marca hasta tres resultados con «Preguntar por este» para que lea sus
            pliegos y los compare.
          </p>
          {consulta && seleccion.length === 0 && (
            <Button variant="outline" size="sm" onClick={() => onPreguntar(consulta, { nueva: true })}>
              <span className="truncate">Responder «{consulta}»</span>
            </Button>
          )}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
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

      <form onSubmit={enviar} className="mt-2 flex gap-2">
        <Input
          aria-label="Pregunta al asistente"
          placeholder={seleccion.length > 0 ? "Pregunta por lo marcado…" : "Haz una pregunta…"}
          value={pregunta}
          onChange={(e) => setPregunta(e.target.value)}
          className="flex-1"
        />
        {chat.loading ? (
          <Button type="button" variant="outline" onClick={chat.stop}>
            Detener
          </Button>
        ) : (
          <Button type="submit" disabled={pregunta.trim().length < 3}>
            Preguntar
          </Button>
        )}
      </form>
    </Panel>
  );
}
