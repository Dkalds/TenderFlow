"use client";

/**
 * El Investigador y el asistente único: sobre qué responde y con qué ajustes.
 *
 * Hasta 2026-10 el Investigador tenía su propio chat al lado de la lista, con
 * su conversación. Hoy abre el asistente de toda la consola
 * (`lib/asistente-store.ts`) con su contexto: todas las licitaciones, o hasta
 * tres resultados marcados en la lista (el asistente lee entonces sus pliegos
 * y cita de dónde saca cada dato), y sus ajustes —modelo, contexto, ámbito y
 * «tal cual»—. El alcance es de cada pregunta, así que marcar o desmarcar no
 * reinicia la conversación; y como el panel no es modal, se marca con él
 * abierto y la siguiente pregunta ya va sobre lo marcado.
 */

import { useCallback, useEffect, useMemo } from "react";
import type { FiltrosCorpus, OpcionesCorpus } from "@/lib/api-types";
import {
  MAX_EXPEDIENTES_ASISTENTE,
  useAsistente,
  type ExpedienteContexto,
  type OpcionesAsistente,
} from "@/lib/asistente-store";
import type { InvestigadorConfig, SearchResult } from "../_lib/types";

export { MAX_EXPEDIENTES_ASISTENTE };

/**
 * Expedientes de contexto que admite una pregunta sobre todas las licitaciones
 * (`top_k` de `POST /ask`). «Resultados» llega a 50 para la lista; mandar ese
 * número al asistente era un 422.
 */
const MAX_CONTEXTO_ASISTENTE = 20;

/** Un resultado marcado para preguntarle al asistente por él. */
export type ExpedienteMarcado = ExpedienteContexto;

const SIN_MARCAR: ExpedienteMarcado[] = [];

export interface AsistenteInvestigador {
  /** Pregunta sobre lo marcado (o sobre todo, si no hay nada). Con `nueva`, en una conversación nueva. */
  preguntar: (pregunta: string, opciones?: { nueva?: boolean }) => void;
  /** Pregunta sobre todas las licitaciones, en una conversación nueva. */
  preguntarSobreTodo: (pregunta: string) => void;
  /** Abre el asistente sobre lo marcado, sin preguntar nada todavía. */
  abrir: () => void;
  seleccion: ExpedienteMarcado[];
  alternarSeleccion: (resultado: SearchResult) => void;
  quitarSeleccion: (id: string) => void;
  soltarSeleccion: () => void;
  /** Ya hay tres marcados: no cabe otro. */
  seleccionLlena: boolean;
}

export function useAsistenteInvestigador({
  config,
  filtros,
  talCual,
}: {
  config: InvestigadorConfig;
  filtros: FiltrosCorpus;
  talCual: boolean;
}): AsistenteInvestigador {
  const contexto = useAsistente((s) => s.contexto);
  const abrirAsistente = useAsistente((s) => s.abrir);
  const alternarExpediente = useAsistente((s) => s.alternarExpediente);
  const quitarExpediente = useAsistente((s) => s.quitarExpediente);
  const soltarExpedientes = useAsistente((s) => s.soltarExpedientes);
  const fijarOpciones = useAsistente((s) => s.fijarOpciones);

  // Solo es selección del Investigador lo que marcó el Investigador: el
  // expediente de una ficha abierta antes no aparece marcado en la lista.
  const seleccion = contexto.origen === "investigador" ? contexto.expedientes : SIN_MARCAR;

  const opcionesCon = useCallback(
    (sinInterpretar: boolean): OpcionesAsistente => {
      const extras: OpcionesCorpus = sinInterpretar ? { ...filtros, interpretar: false } : filtros;
      return {
        model: config.model || undefined,
        topK: Math.min(config.topK, MAX_CONTEXTO_ASISTENTE),
        extras,
      };
    },
    [config.model, config.topK, filtros],
  );

  // Los ajustes siguen a la pantalla mientras el contexto del asistente sea del
  // Investigador. Sin esto solo se fijaban al abrir o al marcar, y la pregunta
  // de seguimiento que se escribe en el panel salía con el modelo, el ámbito o
  // el «tal cual» de antes de cambiarlos. `fijarOpciones` no hace nada si el
  // contexto es de otra pantalla.
  useEffect(() => {
    fijarOpciones("investigador", opcionesCon(talCual));
  }, [fijarOpciones, opcionesCon, talCual]);

  const enviar = useCallback(
    (pregunta: string, expedientes: ExpedienteMarcado[], nueva: boolean, sinInterpretar: boolean) => {
      if (!pregunta.trim()) return;
      abrirAsistente({
        contexto: { expedientes, origen: "investigador" },
        opciones: opcionesCon(sinInterpretar),
        pregunta,
        nueva,
      });
    },
    [abrirAsistente, opcionesCon],
  );

  const preguntar = useCallback(
    (pregunta: string, opcionesDeEnvio?: { nueva?: boolean }) =>
      enviar(pregunta, seleccion, Boolean(opcionesDeEnvio?.nueva), talCual),
    [enviar, seleccion, talCual],
  );

  // La pregunta que llega de la caja de arriba es una consulta nueva, y una
  // consulta nueva se vuelve a leer: «tal cual» era una decisión sobre la
  // anterior. Si heredara ese ajuste, la lista se buscaría leyendo los filtros
  // de la frase y la respuesta, sin leerlos.
  const preguntarSobreTodo = useCallback((pregunta: string) => enviar(pregunta, [], true, false), [enviar]);

  const abrir = useCallback(
    () =>
      abrirAsistente({
        contexto: { expedientes: seleccion, origen: "investigador" },
        opciones: opcionesCon(talCual),
      }),
    [abrirAsistente, seleccion, opcionesCon, talCual],
  );

  const alternarSeleccion = useCallback(
    (resultado: SearchResult) => {
      alternarExpediente(
        { id: resultado.id_externo, titulo: resultado.titulo ?? resultado.id_externo },
        "investigador",
      );
      // Marcar no pasa por `abrir`: los ajustes tienen que viajar igual.
      fijarOpciones("investigador", opcionesCon(talCual));
    },
    [alternarExpediente, fijarOpciones, opcionesCon, talCual],
  );

  const quitarSeleccion = useCallback(
    (id: string) => {
      if (seleccion.some((s) => s.id === id)) quitarExpediente(id);
    },
    [quitarExpediente, seleccion],
  );

  const soltarSeleccion = useCallback(() => soltarExpedientes("investigador"), [soltarExpedientes]);

  return useMemo(
    () => ({
      preguntar,
      preguntarSobreTodo,
      abrir,
      seleccion,
      alternarSeleccion,
      quitarSeleccion,
      soltarSeleccion,
      seleccionLlena: seleccion.length >= MAX_EXPEDIENTES_ASISTENTE,
    }),
    [preguntar, preguntarSobreTodo, abrir, seleccion, alternarSeleccion, quitarSeleccion, soltarSeleccion],
  );
}
