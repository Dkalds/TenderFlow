/**
 * La semana de «Tu día» en carriles: qué vence cada día.
 *
 * No decide nada: la banda de urgencia (`urgencia`) y los días que quedan
 * (`dias_restantes`) vienen calculados de `GET /pursuits/agenda` (ADR-014).
 * Aquí solo se colocan las filas en el carril de su día, en el orden en que
 * llegaron, y los días seguidos sin nada se juntan en un hueco: siete columnas
 * vacías decían «libre» siete veces y empujaban lo urgente fuera de la vista.
 */

import { formatDiaSemana } from "@/lib/utils";
import type { PipelineAgendaItem } from "@/hooks/use-pursuits";

/** Días por delante que caben en la banda: los de la urgencia `semana`. */
export const DIAS_SEMANA = 7;

export type TonoCarril = "vencido" | "hoy" | "dia";

export type TramoSemana =
  | {
      tipo: "carril";
      clave: string;
      etiqueta: string;
      tono: TonoCarril;
      items: PipelineAgendaItem[];
    }
  | { tipo: "libre"; clave: string; etiqueta: string };

function diaDentroDe(hoy: Date, dias: number): Date {
  return new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() + dias);
}

export function semanaEnCarriles(
  items: readonly PipelineAgendaItem[],
  hoy: Date,
  dias = DIAS_SEMANA,
): TramoSemana[] {
  const tramos: TramoSemana[] = [];

  const vencidos = items.filter((item) => item.urgencia === "vencida");
  if (vencidos.length > 0) {
    tramos.push({ tipo: "carril", clave: "vencido", etiqueta: "Vencido", tono: "vencido", items: vencidos });
  }
  tramos.push({
    tipo: "carril",
    clave: "hoy",
    etiqueta: "Hoy",
    tono: "hoy",
    items: items.filter((item) => item.urgencia === "hoy"),
  });

  // Días vacíos pendientes de cerrar en un solo hueco.
  let libres: number[] = [];
  const cerrarHueco = () => {
    if (libres.length === 0) return;
    const primero = formatDiaSemana(diaDentroDe(hoy, libres[0]));
    const ultimo = formatDiaSemana(diaDentroDe(hoy, libres[libres.length - 1]));
    tramos.push({
      tipo: "libre",
      clave: `libre-${libres[0]}`,
      etiqueta: libres.length === 1 ? primero : `${primero} – ${ultimo}`,
    });
    libres = [];
  };

  for (let dia = 1; dia <= dias; dia += 1) {
    const delDia = items.filter((item) => item.urgencia === "semana" && item.dias_restantes === dia);
    if (delDia.length === 0) {
      libres.push(dia);
      continue;
    }
    cerrarHueco();
    tramos.push({
      tipo: "carril",
      clave: `dia-${dia}`,
      etiqueta: formatDiaSemana(diaDentroDe(hoy, dia)),
      tono: "dia",
      items: delDia,
    });
  }
  cerrarHueco();

  return tramos;
}
