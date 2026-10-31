/**
 * Vocabulario del panel de publicaciones y sus dos derivaciones puras.
 *
 * Ninguna de las dos agrega nada: `puntosScatter` sólo traduce los items que ya
 * vinieron del backend a coordenadas, y `leyendaEstados` lee los colores de los
 * puntos que efectivamente se dibujan. Los totales, la serie por día y el
 * histograma los calcula el backend sobre el periodo completo (ADR-014).
 */

import { getEstadoChartColor } from "@/lib/chart-colors";
import { formatDate } from "@/lib/utils";
import type { TimelineItem } from "../types";

/** Los tres cortes del mismo periodo. */
export type Corte = "ritmo" | "importes" | "dispersion";

export const TABS: { key: Corte; label: string }[] = [
  { key: "ritmo", label: "Ritmo" },
  { key: "importes", label: "Importes" },
  { key: "dispersion", label: "Dispersión" },
];

/**
 * Alto común de los tres cortes: cambiar de pestaña no debe mover la página.
 * Bajó de 288 a 224 con el Resumen compacto (2026-10-31): el panel comparte
 * fila con la composición y el mapa, y su alto marca el de la fila.
 */
export const ALTO = 224;

/**
 * El mismo alto como mínimo, en clase: el gráfico crece hasta el alto de la
 * fila cuando la composición o el mapa de al lado son más altos, en vez de
 * dejar un hueco bajo el panel, y nunca baja de `ALTO`.
 */
export const ALTO_MINIMO = "min-h-[224px]";

export const HINTS: Record<Corte, string> = {
  ritmo: "por día · pulsa una barra para acotar el ámbito a ese día",
  importes: "por tramo de importe",
  dispersion: "fecha e importe (escala logarítmica) · color por estado",
};

/** «desde el 27 jul 2026» / «entre el 1 jul y el 31 jul de 2026». */
export function ventanaLabel(desde: string, hasta: string | null): string {
  return hasta ? `entre el ${formatDate(desde)} y el ${formatDate(hasta)}` : `desde el ${formatDate(desde)}`;
}

export interface PuntoScatter {
  x: number;
  y: number;
  id: string;
  titulo: string;
  estado: string;
  fill: string;
}

/**
 * Puntos dibujables. Un eje logarítmico no admite el cero, así que los
 * expedientes sin importe declarado quedan fuera — y se dicen, en vez de
 * desaparecer en la franja del eje como hacían antes.
 */
export function puntosScatter(items: TimelineItem[]): PuntoScatter[] {
  return items
    .filter((item) => (item.importe ?? 0) > 0)
    .map((item) => ({
      x: new Date(item.fecha_publicacion ?? "").getTime(),
      y: item.importe as number,
      id: item.id_externo,
      titulo: item.titulo ?? "",
      estado: item.estado ?? "",
      fill: getEstadoChartColor(item.estado),
    }));
}

/** Estados presentes en la nube, en orden de aparición, con su color. */
export function leyendaEstados(puntos: PuntoScatter[]): [string, string][] {
  const vistos = new Map<string, string>();
  for (const punto of puntos) {
    if (punto.estado && !vistos.has(punto.estado)) vistos.set(punto.estado, punto.fill);
  }
  return [...vistos.entries()];
}

/** Un tramo de fin de semana en el eje del ritmo: del primer al último día. */
export interface TramoFinDeSemana {
  desde: string;
  hasta: string;
}

/** `YYYY-MM-DD` como fecha local: sin pasar por UTC, el día no cambia de zona. */
function diaLocal(periodo: string): Date | null {
  const partes = /^(\d{4})-(\d{2})-(\d{2})/.exec(periodo);
  if (!partes) return null;
  return new Date(Number(partes[1]), Number(partes[2]) - 1, Number(partes[3]));
}

const UN_DIA_MS = 24 * 60 * 60 * 1000;

/**
 * Los sábados y domingos del eje, juntos cuando van seguidos: sábado y domingo
 * son una sola banda. No mira el dato, solo la fecha de cada barra; el eje solo
 * tiene los días con actividad, así que un fin de semana sin publicaciones no
 * tiene barra y no se marca.
 */
export function tramosFinDeSemana(periodos: readonly string[]): TramoFinDeSemana[] {
  const tramos: TramoFinDeSemana[] = [];
  let previo: Date | null = null;
  for (const periodo of periodos) {
    const dia = diaLocal(periodo);
    const esFinde = dia !== null && (dia.getDay() === 0 || dia.getDay() === 6);
    if (!esFinde || dia === null) {
      previo = null;
      continue;
    }
    const ultimo = tramos.at(-1);
    // Contiguo si el día anterior del eje es el día anterior del calendario
    // (con redondeo: un cambio de hora no deja el salto en 24 h justas).
    if (ultimo && previo && Math.round((dia.getTime() - previo.getTime()) / UN_DIA_MS) === 1) {
      ultimo.hasta = periodo;
    } else {
      tramos.push({ desde: periodo, hasta: periodo });
    }
    previo = dia;
  }
  return tramos;
}
