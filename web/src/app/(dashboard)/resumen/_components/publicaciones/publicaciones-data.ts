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

/** Alto común de los tres cortes: cambiar de pestaña no debe mover la página. */
export const ALTO = 288;

export const HINTS: Record<Corte, string> = {
  ritmo: "publicaciones por día · pulsa una barra para acotar el ámbito a ese día",
  importes: "cuántas licitaciones caen en cada tramo de importe",
  dispersion: "fecha × importe (escala logarítmica) · color por estado",
};

/** «desde el 27 jul 2026» / «entre el 1 jul y el 31 jul de 2026». */
export function ventanaLabel(desde: string, hasta: string | null): string {
  return hasta
    ? `entre el ${formatDate(desde)} y el ${formatDate(hasta)}`
    : `desde el ${formatDate(desde)}`;
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
