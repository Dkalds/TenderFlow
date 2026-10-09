/**
 * Lo que una fila de la agenda **dice**: su título, el aviso de cuánto falta,
 * el día y la línea de contexto. El otro medio del vocabulario —tramos,
 * colores, iconos, contadores— está en `agenda-meta.ts`.
 *
 * Nada de aquí decide en qué tramo cae una fila ni cuántos días le quedan: eso
 * viene de `GET /pursuits/agenda` (ADR-014). Aquí solo se redacta.
 */

import { EMPTY, formatDate, formatDiaCorto, truncate } from "@/lib/utils";
import { statusLabel } from "@/components/pursuits/pursuit-presenters";
import type { PipelineAgendaItem, PursuitStatus } from "@/hooks/use-pursuits";
import { bandaDe, esVentanaAbierta } from "./agenda-meta";

/**
 * El estado de la oportunidad, dicho dentro de una frase. El tablero titula su
 * columna «Decisión» y ahí se entiende; suelto entre puntos («Plazo de
 * presentación · Decisión · Ana») no decía de qué.
 */
export function estadoEnFrase(status: PursuitStatus): string {
  return status === "go_no_go" ? "Pendiente de Go/No-Go" : statusLabel(status);
}

/**
 * Qué es la fecha que la fila enseña. Es la mitad del rediseño: un chip de «3 d»
 * sin esto no dice si lo que vence es la licitación, una tarea propia o la
 * ventana en la que se espera la relicitación de un contrato ya ganado.
 */
export function tipoDeFecha(item: PipelineAgendaItem): string {
  switch (item.due_kind) {
    case "plazo":
      return "Plazo de presentación";
    case "accion":
      return "Acción";
    case "fin_contrato":
      return "Fin de contrato";
    case "relicitacion":
      return "Ventana de relicitación";
    default:
      // `due_kind` es opcional en el contrato (los clientes viejos construyen
      // items sin él): se cae al `kind`, que siempre viene.
      return item.kind === "senal" ? "Plazo de presentación" : "Fin de contrato";
  }
}

/**
 * De dónde sale la fecha de fin de un contrato, en las dos familias que el
 * backend usa: la cartera propia (`publicada | duracion | prorroga | manual`) y
 * las renovaciones de mercado (`real | estimada_*`). Una fecha calculada con la
 * duración no vale lo mismo que una publicada, y sobre ella se decide cuándo
 * empezar a preparar la relicitación.
 */
const ORIGEN_FECHA_FIN: Record<string, string> = {
  publicada: "fecha publicada",
  real: "fecha publicada",
  duracion: "fecha estimada por duración",
  estimada_inicio: "fecha estimada por duración",
  estimada_adjudicacion: "fecha estimada por duración",
  prorroga: "fecha con prórroga aplicada",
  manual: "fecha introducida a mano",
  desconocida: "sin fecha de fin publicada",
};

export function origenFechaFin(origen: string | null | undefined): string | null {
  return origen ? (ORIGEN_FECHA_FIN[origen] ?? null) : null;
}

/** El título de la fila. En una tarea, lo que hay que hacer — no el expediente. */
export function tituloDe(item: PipelineAgendaItem): string {
  if (item.kind === "tarea") {
    return item.tarea_texto ?? item.next_action ?? item.titulo ?? item.licitacion_id;
  }
  return item.titulo ?? item.licitacion_id;
}

export function plazoChip(item: PipelineAgendaItem): string {
  // La oferta está entregada: los días que hayan pasado desde el plazo no son
  // un retraso, y contarlos en rojo decía lo contrario.
  if (bandaDe(item) === "en_resolucion") return "presentada";
  if (item.dias_restantes == null) return EMPTY;
  if (esVentanaAbierta(item)) return "abierta";
  if (item.urgencia === "hoy") return item.due_hora ? `hoy ${item.due_hora}` : "hoy";
  if (item.dias_restantes < 0) return `−${Math.abs(item.dias_restantes)} d`;
  return `${item.dias_restantes} d`;
}

/** A partir de cuántos días el día de la semana deja de decir nada. */
const DIAS_CON_DIA_DE_LA_SEMANA = 30;

/**
 * El día del compromiso: «jue 15 oct» cuando cae cerca —el día de la semana es
 * la mitad del dato: «3 d» no dice que es domingo— y «31 ene 2027» cuando está
 * lejos, donde lo que hace falta es el año.
 *
 * La distancia sale de `dias_restantes`, que manda la API: aquí no se mira el
 * reloj.
 */
export function fechaDeFila(item: PipelineAgendaItem): string | null {
  if (!item.due_date) return null;
  const lejos =
    item.dias_restantes == null || Math.abs(item.dias_restantes) > DIAS_CON_DIA_DE_LA_SEMANA;
  if (lejos) return formatDate(item.due_date);
  // Medianoche local, no UTC: `new Date("2026-08-16")` es el día 15 por la
  // tarde al oeste de Greenwich.
  const dia = new Date(`${item.due_date}T00:00:00`);
  return isNaN(dia.getTime()) ? formatDate(item.due_date) : formatDiaCorto(dia);
}

function plural(n: number, uno: string, varios: string): string {
  return `${n} ${n === 1 ? uno : varios}`;
}

/**
 * La línea que hay bajo el título: primero **qué clase de fecha** es la del
 * chip, después el contexto que hace falta para decidir sin abrir nada.
 *
 * `anidada` es la tarea pintada justo debajo de su oportunidad: no repite de
 * quién es, que es lo que tiene encima.
 */
export function metaLinea(item: PipelineAgendaItem, { anidada = false } = {}): string {
  const partes: string[] = [tipoDeFecha(item)];

  if (item.kind === "pursuit") {
    if (item.due_hora) partes[0] = `${partes[0]} a las ${item.due_hora}`;
    if (item.status) partes.push(estadoEnFrase(item.status));
    // Antes que el responsable y el órgano: la línea se corta por la derecha
    // cuando no cabe, y lo que se pierde tiene que ser lo que menos decide.
    if (item.tareas_abiertas) {
      partes.push(plural(item.tareas_abiertas, "tarea abierta", "tareas abiertas"));
    }
    if (item.responsible_name) partes.push(item.responsible_name);
    if (item.organo) partes.push(truncate(item.organo, 40));
    return partes.join(" · ");
  }
  if (item.kind === "tarea") {
    if (anidada) return "Acción de esta oportunidad";
    // El título de la fila es la tarea, así que aquí va el expediente: sin él,
    // cuatro «Revisar pliego» seguidas son indistinguibles.
    partes[0] = `Acción de «${truncate(item.titulo ?? item.licitacion_id, 40)}»`;
    if (item.status) partes.push(estadoEnFrase(item.status));
    return partes.join(" · ");
  }
  if (item.kind === "senal") {
    if (item.due_hora) partes[0] = `${partes[0]} a las ${item.due_hora}`;
    if (item.rule_nombre) partes.push(`Regla «${item.rule_nombre}»`);
  }
  if (item.kind === "renovacion" && item.adjudicatario) {
    partes.push(`Adjudicatario: ${truncate(item.adjudicatario, 32)}`);
  }
  if (item.kind === "contrato" && esVentanaAbierta(item)) {
    partes[0] = `${partes[0]} abierta hace ${Math.abs(item.dias_restantes ?? 0)} d`;
  }
  if (item.organo) partes.push(truncate(item.organo, 40));
  if (item.kind === "contrato") {
    partes.push(
      item.due_kind === "relicitacion" && item.fecha_fin_efectiva
        ? `contrato vence el ${formatDate(item.fecha_fin_efectiva)}`
        : (origenFechaFin(item.fecha_fin_origen) ?? ""),
    );
  }
  return partes.filter(Boolean).join(" · ");
}
