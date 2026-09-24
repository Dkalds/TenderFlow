/**
 * Vocabulario visual de la agenda: las bandas de urgencia que manda el backend,
 * su color, y **de qué clase es la fecha** de cada compromiso.
 *
 * Ninguna de estas tablas decide *en qué banda cae* un ítem ni *en qué orden*
 * va — eso viene en `item.urgencia` desde `GET /pursuits/agenda` (ADR-014).
 * Aquí sólo se traduce a etiqueta, tono e icono.
 *
 * Lo exporta también el Resumen (`resumen/_components/tu-dia.tsx`): las dos
 * superficies enseñan las mismas cinco clases de compromiso, y con dos mapas de
 * iconos distintos la misma fila se leía de dos maneras según por dónde
 * entraras. Un solo vocabulario, dos pantallas.
 */

import { Bell, Briefcase, CalendarClock, RefreshCcw, SquareCheck, type LucideIcon } from "lucide-react";
import { EMPTY, formatDate, truncate } from "@/lib/utils";
import { statusLabel } from "@/components/pursuits/pursuit-presenters";
import type { AgendaKind, AgendaUrgencia, PipelineAgendaItem } from "@/hooks/use-pursuits";

/**
 * Rejilla de la tabla — solo a partir de `md`. Por debajo, ficha en columna.
 * La última columna creció de 96 a 150 px: la acción del contrato es «Preparar
 * renovación», y a 96 px se recortaba a «Preparar r…».
 */
export const GRID = "md:grid-cols-[72px_26px_1fr_110px_150px] md:gap-3 md:px-3.5";

export const BANDAS: { key: AgendaUrgencia; label: string; tone: string }[] = [
  { key: "vencida", label: "Vencidas", tone: "text-destructive" },
  { key: "hoy", label: "Hoy", tone: "text-destructive" },
  { key: "semana", label: "Próximos 7 días", tone: "text-[hsl(var(--warning))]" },
  { key: "mes", label: "Próximos 30 días", tone: "text-muted-foreground" },
  { key: "despues", label: "Más adelante", tone: "text-muted-foreground" },
  { key: "sin_fecha", label: "Sin fecha", tone: "text-muted-foreground" },
];

export const CHIP_POR_BANDA: Record<AgendaUrgencia, string> = {
  vencida: "bg-destructive/12 text-destructive",
  hoy: "bg-destructive/12 text-destructive",
  semana: "bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]",
  mes: "bg-secondary text-foreground/80",
  despues: "bg-muted-foreground/10 text-muted-foreground",
  sin_fecha: "bg-muted-foreground/10 text-muted-foreground",
};

/**
 * Los dos carriles de la agenda. `compromisos` es lo que la organización ya ha
 * decidido trabajar —plazos, acciones y contratos propios—; `triaje`, lo que
 * las reglas proponen y todavía no ha decidido nadie. Repartir por `kind` no es
 * reordenar: dentro de cada carril las filas conservan el orden del backend.
 */
export type Carril = "compromisos" | "triaje";

export function carrilDe(item: PipelineAgendaItem): Carril {
  return item.kind === "senal" ? "triaje" : "compromisos";
}

/**
 * El contrato tiene dos iconos: `Briefcase` cuando lo que vence es el contrato
 * y `RefreshCcw` cuando lo que se abre es su ventana de relicitación — es otra
 * cosa la que hay que hacer, y el icono lo dice antes que el texto.
 */
export type IconoAgenda = AgendaKind | "relicitacion";

/**
 * Tabla y no función que devuelva el componente: el compilador de React prohíbe
 * *crear* un componente durante el render (`react-hooks/static-components`), y
 * una llamada que retorna uno cuenta como tal. Con la tabla, el sitio de uso
 * hace `ICONOS[claseDeIcono(item)]` — una lectura, no una creación.
 */
export const ICONOS: Record<IconoAgenda, LucideIcon> = {
  pursuit: CalendarClock,
  tarea: SquareCheck,
  contrato: Briefcase,
  relicitacion: RefreshCcw,
  senal: Bell,
  renovacion: CalendarClock,
};

export function claseDeIcono(item: PipelineAgendaItem): IconoAgenda {
  return item.kind === "contrato" && item.due_kind === "relicitacion"
    ? "relicitacion"
    : item.kind;
}

const ETIQUETA_POR_KIND: Record<AgendaKind, string> = {
  pursuit: "Oportunidad",
  tarea: "Tarea",
  contrato: "Contrato",
  senal: "Señal",
  renovacion: "Renovación",
};

export function etiquetaKind(item: PipelineAgendaItem): string {
  if (item.kind === "contrato" && item.due_kind === "relicitacion") return "Relicitación";
  return ETIQUETA_POR_KIND[item.kind];
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

/**
 * Identidad de una fila. Lleva `tarea_id` porque una oportunidad y sus tareas
 * comparten `licitacion_id`: sin él, React reutilizaba el nodo de la primera
 * tarea para la segunda y el inspector se quedaba con el detalle anterior.
 */
export function claveDe(item: PipelineAgendaItem): string {
  return `${item.kind}:${item.licitacion_id}:${item.tarea_id ?? ""}`;
}

/** El título de la fila. En una tarea, lo que hay que hacer — no el expediente. */
export function tituloDe(item: PipelineAgendaItem): string {
  if (item.kind === "tarea") {
    return item.tarea_texto ?? item.next_action ?? item.titulo ?? item.licitacion_id;
  }
  return item.titulo ?? item.licitacion_id;
}

/** Dónde vive el compromiso: su oportunidad, o la ficha del expediente. */
export function destinoDe(item: PipelineAgendaItem): string {
  const pursuit =
    item.kind === "contrato" ? (item.renovacion_pursuit_id ?? item.pursuit_id) : item.pursuit_id;
  if (pursuit != null && item.kind !== "senal" && item.kind !== "renovacion") {
    return `/oportunidades/${pursuit}`;
  }
  return `/detalle?lic=${encodeURIComponent(item.licitacion_id)}`;
}

/**
 * Días que se pospone una señal desde la agenda: una semana de trabajo. Vive
 * aquí y no en el componente porque el gesto (el hook) y el botón lo comparten.
 */
export const DIAS_POSPONER = 7;

export const SHORTCUTS = [
  { key: "J K", label: "navegar" },
  { key: "S", label: "seguir" },
  { key: "X", label: "descartar" },
  { key: "C", label: "completar tarea" },
  { key: "⏎", label: "abrir" },
];

export function plazoChip(item: PipelineAgendaItem): string {
  if (item.dias_restantes == null) return EMPTY;
  if (item.urgencia === "hoy") return "hoy";
  if (item.dias_restantes < 0) return `−${Math.abs(item.dias_restantes)} d`;
  return `${item.dias_restantes} d`;
}

/**
 * La línea que hay bajo el título: primero **qué clase de fecha** es la del
 * chip, después el contexto que hace falta para decidir sin abrir nada.
 */
export function metaLinea(item: PipelineAgendaItem): string {
  const partes: string[] = [tipoDeFecha(item)];

  if (item.kind === "pursuit") {
    if (item.status) partes.push(statusLabel(item.status));
    if (item.responsible_name) partes.push(item.responsible_name);
  }
  if (item.kind === "tarea") {
    // El título de la fila es la tarea, así que aquí va el expediente: sin él,
    // cuatro «Revisar pliego» seguidas son indistinguibles.
    partes[0] = `Acción de «${truncate(item.titulo ?? item.licitacion_id, 40)}»`;
    if (item.status) partes.push(statusLabel(item.status));
    return partes.join(" · ");
  }
  if (item.kind === "senal" && item.rule_nombre) partes.push(`Regla «${item.rule_nombre}»`);
  if (item.kind === "renovacion" && item.adjudicatario) {
    partes.push(`Adjudicatario: ${truncate(item.adjudicatario, 32)}`);
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
