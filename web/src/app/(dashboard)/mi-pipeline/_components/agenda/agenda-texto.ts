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
 * La oportunidad sigue viva y nadie ha decidido si se va a por ella.
 *
 * Lo dice la API, con la misma regla con la que cuenta «Go/No-Go pendientes»
 * (`cuenta_en`): así lo que el filtro deja y lo que la fila dice no pueden
 * separarse. Antes la fila redactaba por **fase** y el contador contaba por
 * **decisión**, y el filtro dejaba filas que solo decían «Identificada». Una
 * API anterior al campo no lo manda: ahí se mira la decisión, que es lo que hay.
 */
export function sinDecidir(item: PipelineAgendaItem): boolean {
  return item.cuenta_en ? item.cuenta_en.includes("go_no_go") : item.decision === "pending";
}

/**
 * Lo que la fila tiene que decir en alto: que el plazo cae dentro de la semana
 * y la oportunidad sigue sin decidir. Las dos cosas las marca la API
 * (`cuenta_en`); aquí solo se juntan en una palabra.
 */
export function avisoDeFila(item: PipelineAgendaItem): string | null {
  const cuenta = item.cuenta_en ?? [];
  return item.kind === "pursuit" && cuenta.includes("go_no_go") && cuenta.includes("plazo_semana")
    ? "Sin decidir"
    : null;
}

/**
 * La fase de la oportunidad, dicha dentro de una frase, y si falta la decisión.
 *
 * El tablero titula su columna «Decisión» y ahí se entiende; suelto entre
 * puntos («Plazo de presentación · Decisión · Ana») no decía de qué.
 * `sinColetilla` es para la fila que ya lleva el aviso «Sin decidir» delante:
 * decirlo dos veces en la misma línea no lo hace más urgente.
 */
export function estadoDeFila(
  item: PipelineAgendaItem,
  { sinColetilla = false }: { sinColetilla?: boolean } = {},
): string | null {
  const status: PursuitStatus | null | undefined = item.status;
  if (!status) return null;
  const pendiente = sinDecidir(item) && !sinColetilla;
  if (status === "go_no_go") return pendiente ? "Pendiente de Go/No-Go" : "En decisión";
  return pendiente ? `${statusLabel(status)}, sin decidir` : statusLabel(status);
}

const CIERRE_POR_ESTADO: Record<string, { chip: string; frase: string }> = {
  RES: { chip: "resuelta", frase: "Licitación resuelta" },
  ADJ: { chip: "adjudicada", frase: "Licitación adjudicada" },
  ANUL: { chip: "anulada", frase: "Licitación anulada" },
};

/**
 * En qué quedó la licitación de una oportunidad que sigue abierta, o `null` si
 * sigue admitiendo ofertas. Que está cerrada lo decide la API
 * (`expediente_cerrado`); aquí solo se redacta, con el adjudicatario delante
 * cuando se conoce: es lo que permite cerrarla sin abrir nada.
 */
export function cierreDelExpediente(item: PipelineAgendaItem): string | null {
  if (item.kind !== "pursuit" || !item.expediente_cerrado) return null;
  if (item.adjudicatario) return `Adjudicada a ${truncate(item.adjudicatario, 48)}`;
  return CIERRE_POR_ESTADO[item.expediente_estado ?? ""]?.frase ?? "Licitación cerrada";
}

/** Lo mismo en una palabra, para el aviso de la fila que no tiene días que contar. */
function chipDeCierre(item: PipelineAgendaItem): string | null {
  if (item.kind !== "pursuit" || !item.expediente_cerrado) return null;
  if (item.adjudicatario) return "adjudicada";
  return CIERRE_POR_ESTADO[item.expediente_estado ?? ""]?.chip ?? "cerrada";
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
  // Por cerrar sin un plazo vencido que contar —no hay fecha, o la licitación
  // se resolvió antes de que llegara—: «5 d» diría que queda tiempo.
  if (bandaDe(item) === "plazo_pasado" && !(item.dias_restantes != null && item.dias_restantes < 0)) {
    return chipDeCierre(item) ?? EMPTY;
  }
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
    // Delante de todo, antes incluso que la clase de fecha: si la licitación
    // ya está resuelta el resto de la línea se lee de otra manera, y en la
    // ficha móvil —donde la línea se corta a los 200 px— es lo único que cabe.
    const cierre = cierreDelExpediente(item);
    if (cierre) partes.unshift(cierre);
    const estado = estadoDeFila(item, { sinColetilla: avisoDeFila(item) != null });
    if (estado) partes.push(estado);
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
    // La fase de su oportunidad, sin la coletilla: la decisión es de la
    // oportunidad y se dice en su fila, no en cada tarea suya.
    const estado = estadoDeFila(item, { sinColetilla: true });
    if (estado) partes.push(estado);
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
