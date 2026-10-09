/**
 * Las empresas vigiladas, como funciones puras.
 *
 * La actividad y las señales (territorio nuevo, nicho nuevo, racha) las calcula
 * el backend sobre adjudicaciones reales (`/competitive/watchlist/movimientos`).
 * Aquí solo hay geometría —dónde cae un movimiento en el carril de la ventana—
 * y el cruce por identidad que deja marcar en el mapa y en el ranking las
 * empresas que vigilas.
 */

import type { Schemas } from "@/lib/api-types";

import type { Competitor } from "./competidores-types";

export type Movimientos = Schemas["MovimientosVigiladasResult"];
export type Senal = Schemas["SenalCompetitiva"];

const MS_DIA = 24 * 60 * 60 * 1000;

/** Medianoche UTC del día de una fecha ISO; `null` si no lo es. */
function diaUtc(fecha: string): number | null {
  const partes = /^(\d{4})-(\d{2})-(\d{2})/.exec(fecha);
  if (!partes) return null;
  return Date.UTC(Number(partes[1]), Number(partes[2]) - 1, Number(partes[3]));
}

/**
 * Posición de una fecha dentro de la ventana, de 0 (el primer día) a 100.
 *
 * Una fecha fuera de la ventana se queda en el borde: la señal existe y la
 * mandó la API, así que no se esconde; el carril solo no puede situarla mejor.
 */
export function posicionEnVentana(
  fecha: string | null | undefined,
  desde: string,
  dias: number,
): number | null {
  if (!fecha || dias <= 0) return null;
  const dia = diaUtc(fecha);
  const inicio = diaUtc(desde);
  if (dia == null || inicio == null) return null;
  const pct = ((dia - inicio) / (dias * MS_DIA)) * 100;
  return Math.min(100, Math.max(0, pct));
}

export interface MarcaCarril {
  tipo: Senal["tipo"];
  /** Posición en el carril, de 0 a 100. */
  x: number;
  titulo: string;
  fecha: string;
}

export interface Carril {
  empresa_id: number;
  nombre: string;
  adjudicaciones: number;
  importe: number;
  marcas: MarcaCarril[];
}

/**
 * Un carril por empresa vigilada, en el orden de la API, con sus movimientos
 * fechados clavados en la ventana. Una señal sin fecha (una racha no ocurre un
 * día) no va al carril: se lista debajo.
 */
export function carrilesDeVigiladas(data: Movimientos | undefined): Carril[] {
  if (!data) return [];
  const senales = data.senales ?? [];
  return (data.empresas ?? []).map((empresa) => ({
    empresa_id: empresa.empresa_id,
    nombre: empresa.nombre,
    adjudicaciones: empresa.adjudicaciones,
    importe: empresa.importe,
    marcas: senales.flatMap((senal) => {
      if (senal.empresa_id !== empresa.empresa_id || !senal.fecha) return [];
      const x = posicionEnVentana(senal.fecha, data.desde, data.dias);
      return x == null ? [] : [{ tipo: senal.tipo, x, titulo: senal.titulo, fecha: senal.fecha }];
    }),
  }));
}

export function idsVigiladas(data: Movimientos | undefined): Set<number> {
  return new Set((data?.empresas ?? []).map((empresa) => empresa.empresa_id));
}

/**
 * ¿Vigilas a este competidor? Una agrupación lo está si lo está cualquiera de
 * las identidades del maestro que suma; una empresa sin identidad, nunca.
 */
export function esVigilada(c: Competitor, ids: ReadonlySet<number>): boolean {
  if (c.empresa_id != null && ids.has(c.empresa_id)) return true;
  return (c.empresa_ids ?? []).some((id) => ids.has(id));
}
