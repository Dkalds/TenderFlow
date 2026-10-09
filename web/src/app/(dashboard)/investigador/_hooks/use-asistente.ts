"use client";

/**
 * El asistente del Investigador: el hilo y sobre qué responde.
 *
 * El alcance es de cada pregunta, no del hilo: todas las licitaciones, o hasta
 * tres resultados marcados en la lista (el asistente lee entonces sus pliegos
 * y cita de dónde saca cada dato). Se manda con cada envío, así que marcar o
 * desmarcar no reinicia la conversación.
 */

import { useCallback, useMemo, useState } from "react";
import type { FiltrosCorpus, OpcionesCorpus } from "@/lib/api-types";
import { useChat, type UseChatResult } from "@/hooks/use-ask";
import type { InvestigadorConfig, SearchResult } from "../_lib/types";

/**
 * Expedientes que el asistente puede leer a la vez. Es el tope de
 * `ids_externos` en `POST /ask`: con más, cada uno llegaría con dos fragmentos
 * de pliego y la comparación sería de títulos.
 */
export const MAX_EXPEDIENTES_ASISTENTE = 3;

/**
 * Expedientes de contexto que admite una pregunta sobre todas las licitaciones
 * (`top_k` de `POST /ask`). «Resultados» llega a 50 para la lista; mandar ese
 * número al asistente era un 422.
 */
const MAX_CONTEXTO_ASISTENTE = 20;

/** Un resultado marcado para preguntarle al asistente por él. */
export interface ExpedienteMarcado {
  id: string;
  titulo: string;
}

export interface Asistente {
  chat: UseChatResult;
  /** Pregunta sobre lo marcado (o sobre todo, si no hay nada). Con `nueva`, en una conversación nueva. */
  preguntar: (pregunta: string, opciones?: { nueva?: boolean }) => void;
  /** Pregunta sobre todas las licitaciones, en una conversación nueva. */
  preguntarSobreTodo: (pregunta: string) => void;
  seleccion: ExpedienteMarcado[];
  alternarSeleccion: (resultado: SearchResult) => void;
  quitarSeleccion: (id: string) => void;
  soltarSeleccion: () => void;
  /** Ya hay tres marcados: no cabe otro. */
  seleccionLlena: boolean;
  hayConversacion: boolean;
}

export function useAsistente({
  config,
  filtros,
  talCual,
}: {
  config: InvestigadorConfig;
  filtros: FiltrosCorpus;
  talCual: boolean;
}): Asistente {
  const chat = useChat();
  const { send, reset } = chat;
  const [seleccion, setSeleccion] = useState<ExpedienteMarcado[]>([]);

  const opciones = useMemo(
    () => ({ model: config.model || undefined, topK: Math.min(config.topK, MAX_CONTEXTO_ASISTENTE) }),
    [config.model, config.topK],
  );

  const enviar = useCallback(
    (pregunta: string, ids: string[], nueva: boolean, sinInterpretar: boolean) => {
      const q = pregunta.trim();
      if (!q) return;
      if (nueva) reset();
      const extras: OpcionesCorpus = sinInterpretar ? { ...filtros, interpretar: false } : filtros;
      void send(q, { ...opciones, extras, idsExternos: ids });
    },
    [reset, send, opciones, filtros],
  );

  const preguntar = useCallback(
    (pregunta: string, opcionesDeEnvio?: { nueva?: boolean }) =>
      enviar(
        pregunta,
        seleccion.map((s) => s.id),
        Boolean(opcionesDeEnvio?.nueva),
        talCual,
      ),
    [enviar, seleccion, talCual],
  );

  // La pregunta que llega de la caja de arriba es una consulta nueva, y una
  // consulta nueva se vuelve a leer: «tal cual» era una decisión sobre la
  // anterior. Si heredara ese ajuste, la lista se buscaría leyendo los filtros
  // de la frase y la respuesta, sin leerlos.
  const preguntarSobreTodo = useCallback((pregunta: string) => enviar(pregunta, [], true, false), [enviar]);

  const alternarSeleccion = useCallback((resultado: SearchResult) => {
    setSeleccion((prev) => {
      if (prev.some((s) => s.id === resultado.id_externo)) {
        return prev.filter((s) => s.id !== resultado.id_externo);
      }
      if (prev.length >= MAX_EXPEDIENTES_ASISTENTE) return prev;
      return [...prev, { id: resultado.id_externo, titulo: resultado.titulo ?? resultado.id_externo }];
    });
  }, []);

  const quitarSeleccion = useCallback((id: string) => {
    setSeleccion((prev) => prev.filter((s) => s.id !== id));
  }, []);

  const soltarSeleccion = useCallback(() => setSeleccion([]), []);

  return {
    chat,
    preguntar,
    preguntarSobreTodo,
    seleccion,
    alternarSeleccion,
    quitarSeleccion,
    soltarSeleccion,
    seleccionLlena: seleccion.length >= MAX_EXPEDIENTES_ASISTENTE,
    hayConversacion: chat.messages.length > 0 || chat.loading || Boolean(chat.error),
  };
}
