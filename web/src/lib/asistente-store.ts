/**
 * El estado del asistente único: si está abierto, sobre qué responde y qué se
 * le pidió al abrirlo.
 *
 * Hasta 2026-10 la consola tenía tres asistentes con tres estados: el copiloto
 * global (un panel lateral), el chat del Investigador sobre los resultados
 * marcados y la pestaña IA de la ficha, con su resumen. Hacían lo mismo —
 * `POST /ask` con o sin expedientes— y cada uno guardaba su conversación. Hoy
 * hay uno (`components/asistente/asistente-panel.tsx`) y cada entrada lo abre
 * con **su contexto**:
 *
 * - la ficha de una licitación (inspector o ficha completa) y la de una
 *   oportunidad, con su expediente;
 * - el Investigador, con los resultados marcados (hasta tres) o con todas las
 *   licitaciones, y sus ajustes (modelo, contexto, ámbito);
 * - la bandeja de comparación, con sus expedientes;
 * - la barra del Resumen y la paleta, con todas las licitaciones.
 *
 * La conversación vive en el propio panel, montado una sola vez en el layout
 * del dashboard (`overlays-dashboard.tsx`) y que no se desmonta al cerrarse: el
 * contexto es **de cada pregunta**, así que cambiarlo no la borra, y cada turno
 * del hilo recuerda sobre qué se preguntó.
 */
"use client";

import { create } from "zustand";
import type { OpcionesCorpus } from "@/lib/api-types";
import { useUiStore } from "@/lib/ui-store";

/**
 * Expedientes que el asistente puede leer a la vez. Es el tope de
 * `ids_externos` en `POST /ask`: con más, cada uno llegaría con dos fragmentos
 * de pliego y la comparación sería de títulos.
 */
export const MAX_EXPEDIENTES_ASISTENTE = 3;

export interface ExpedienteContexto {
  id: string;
  titulo: string;
}

/** De dónde viene el contexto: decide qué selección toca cada entrada. */
export type OrigenContexto = "ficha" | "oportunidad" | "investigador" | "comparacion";

export interface ContextoAsistente {
  /** Vacío: todas las licitaciones. */
  expedientes: ExpedienteContexto[];
  origen: OrigenContexto | null;
}

/** Ajustes de la pantalla que lo abrió: hoy, los del Investigador. */
export interface OpcionesAsistente {
  model?: string;
  topK?: number;
  /** Filtros del ámbito sobre el corpus (CCAA, tecnología, fechas). */
  extras?: OpcionesCorpus;
}

/** Lo que se pidió al abrir; el panel lo atiende una vez (`clave`). */
export type PedidoAsistente =
  | { tipo: "pregunta"; texto: string; nueva: boolean; clave: number }
  | { tipo: "resumen"; clave: number };

export interface AbrirAsistente {
  /** Ausente: se queda el que había (volver a la conversación). */
  contexto?: ContextoAsistente;
  opciones?: OpcionesAsistente;
  pregunta?: string;
  /** Con `pregunta`: en una conversación nueva. */
  nueva?: boolean;
  /** Resumir el expediente del contexto (solo con uno). */
  resumir?: boolean;
}

interface EstadoAsistente {
  abierto: boolean;
  contexto: ContextoAsistente;
  opciones: OpcionesAsistente;
  pedido: PedidoAsistente | null;
  abrir: (args?: AbrirAsistente) => void;
  cerrar: () => void;
  setAbierto: (abierto: boolean) => void;
  /** Marca o desmarca un expediente; `false` si no cabe. */
  alternarExpediente: (expediente: ExpedienteContexto, origen: OrigenContexto) => boolean;
  quitarExpediente: (id: string) => void;
  /** Suelta los expedientes si los puso `origen` (una búsqueda nueva, por ejemplo). */
  soltarExpedientes: (origen: OrigenContexto) => void;
  /**
   * Los ajustes de `origen`, si el contexto es suyo: marcar resultados en el
   * Investigador no pasa por `abrir`, y la siguiente pregunta tiene que llevar
   * su modelo, su contexto y su ámbito.
   */
  fijarOpciones: (origen: OrigenContexto, opciones: OpcionesAsistente) => void;
  /** El panel ya atendió el pedido `clave`. */
  atender: (clave: number) => void;
  /** Vuelta al estado inicial (tests). */
  reiniciar: () => void;
}

const SIN_CONTEXTO: ContextoAsistente = { expedientes: [], origen: null };

let ultimaClave = 0;

export const useAsistente = create<EstadoAsistente>((set, get) => ({
  abierto: false,
  contexto: SIN_CONTEXTO,
  opciones: {},
  pedido: null,

  abrir: ({ contexto, opciones, pregunta, nueva = false, resumir = false } = {}) => {
    const siguiente = contexto
      ? { ...contexto, expedientes: contexto.expedientes.slice(0, MAX_EXPEDIENTES_ASISTENTE) }
      : get().contexto;
    let pedido = get().pedido;
    if (pregunta?.trim()) {
      pedido = { tipo: "pregunta", texto: pregunta.trim(), nueva, clave: ++ultimaClave };
    } else if (resumir && siguiente.expedientes.length === 1) {
      pedido = { tipo: "resumen", clave: ++ultimaClave };
    }
    // El asistente y la paleta no conviven: abrirlo desde ella la cierra.
    useUiStore.getState().setCommandOpen(false);
    set({
      abierto: true,
      contexto: siguiente,
      // Un contexto nuevo trae sus ajustes, o ninguno: los del Investigador no
      // tienen por qué valer para la ficha de una oportunidad.
      opciones: contexto ? (opciones ?? {}) : (opciones ?? get().opciones),
      pedido,
    });
  },

  cerrar: () => set({ abierto: false }),
  setAbierto: (abierto) => set({ abierto }),

  alternarExpediente: (expediente, origen) => {
    const { contexto } = get();
    const actuales = contexto.origen === origen ? contexto.expedientes : [];
    if (actuales.some((e) => e.id === expediente.id)) {
      const resto = actuales.filter((e) => e.id !== expediente.id);
      set({ contexto: resto.length ? { expedientes: resto, origen } : SIN_CONTEXTO });
      return true;
    }
    if (actuales.length >= MAX_EXPEDIENTES_ASISTENTE) return false;
    set({ contexto: { expedientes: [...actuales, expediente], origen } });
    return true;
  },

  quitarExpediente: (id) => {
    const { contexto } = get();
    const resto = contexto.expedientes.filter((e) => e.id !== id);
    set({ contexto: resto.length ? { ...contexto, expedientes: resto } : SIN_CONTEXTO });
  },

  soltarExpedientes: (origen) => {
    if (get().contexto.origen === origen) set({ contexto: SIN_CONTEXTO });
  },

  fijarOpciones: (origen, opciones) => {
    if (get().contexto.origen === origen) set({ opciones });
  },

  atender: (clave) => {
    if (get().pedido?.clave === clave) set({ pedido: null });
  },

  reiniciar: () => set({ abierto: false, contexto: SIN_CONTEXTO, opciones: {}, pedido: null }),
}));
