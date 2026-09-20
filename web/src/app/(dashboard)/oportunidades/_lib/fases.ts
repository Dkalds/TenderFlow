/**
 * Las fases del tablero y la agrupación por expediente.
 *
 * Sustituye a `carriles.ts`, que agrupaba los ocho estados en cuatro carriles.
 * Agrupar escondía justo lo que el tablero tiene que enseñar: una oportunidad
 * identificada, una en cualificación y una esperando el GO/NO-GO caían en el
 * mismo sitio, así que el tablero no decía en qué punto está cada una y mover
 * una tarjeta no podía significar nada concreto.
 *
 * Ahora hay una columna por estado abierto y una sola para los tres terminales:
 * soltar en «Cerradas» no es mover, es decidir un resultado, y por eso abre el
 * diálogo de cierre en vez de parchear el estado a ciegas.
 */

import { ESTADOS_TERMINALES, esTerminal } from "@/hooks/use-pursuits";
import type { EstadoTerminal, Pursuit, PursuitStatus } from "@/hooks/use-pursuits";

export { ESTADOS_TERMINALES, esTerminal };

export type FaseKey = Exclude<PursuitStatus, EstadoTerminal> | "cerrada";

export interface Fase {
  key: FaseKey;
  titulo: string;
  /** Qué significa estar aquí, en una línea. */
  descripcion: string;
  /** Qué se dice cuando la columna está vacía, nombrando el ámbito. */
  vacio: string;
}

export const FASES: readonly Fase[] = [
  {
    key: "identified",
    titulo: "Identificada",
    descripcion: "Detectada en el Radar, sin cualificar.",
    vacio: "Nada identificado en este ámbito.",
  },
  {
    key: "qualifying",
    titulo: "En cualificación",
    descripcion: "Se está comprobando encaje y solvencia.",
    vacio: "Nada en cualificación.",
  },
  {
    key: "go_no_go",
    titulo: "Decisión",
    descripcion: "Esperando el GO o el NO-GO del comité.",
    vacio: "Ninguna decisión pendiente.",
  },
  {
    key: "preparing",
    titulo: "Preparando oferta",
    descripcion: "Trabajo activo sobre la propuesta.",
    vacio: "Ninguna oferta en preparación.",
  },
  {
    key: "submitted",
    titulo: "Presentada",
    descripcion: "Entregada, pendiente de resultado.",
    vacio: "Nada presentado.",
  },
  {
    key: "cerrada",
    titulo: "Cerradas",
    descripcion: "Ganadas, perdidas o retiradas.",
    vacio: "Nada cerrado todavía.",
  },
] as const;

/** En qué columna del tablero cae un estado. */
export function faseDe(status: PursuitStatus): FaseKey {
  return esTerminal(status) ? "cerrada" : status;
}

export interface GrupoExpediente {
  licitacionId: string;
  titulo: string;
  items: Pursuit[];
}

/**
 * Agrupa las tarjetas de una columna por expediente, conservando el orden en
 * que llegaron: el backend ya ordena por `updated_at`, y reordenar aquí sería
 * fabricar un criterio que el listado no dio.
 */
export function agruparPorExpediente(items: Pursuit[]): GrupoExpediente[] {
  const grupos = new Map<string, GrupoExpediente>();
  for (const item of items) {
    const grupo = grupos.get(item.licitacion_id);
    if (grupo) {
      grupo.items.push(item);
    } else {
      grupos.set(item.licitacion_id, {
        licitacionId: item.licitacion_id,
        titulo: item.tender_title ?? `Licitación ${item.licitacion_id}`,
        items: [item],
      });
    }
  }
  return [...grupos.values()];
}
