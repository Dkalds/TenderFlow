/**
 * Vocabulario visual de la agenda: los tramos que manda el backend, su color,
 * los contadores de la franja y el icono de cada clase de compromiso. Lo que la
 * fila **dice** —título, aviso, día, línea de contexto— está en
 * `agenda-texto.ts`.
 *
 * Ninguna de estas tablas decide *en qué tramo cae* un ítem, *en qué orden* va
 * ni *en qué contador cuenta* — eso viene en `item.banda`, en el orden de la
 * lista y en `item.cuenta_en` desde `GET /pursuits/agenda` (ADR-014). Aquí sólo
 * se traduce a etiqueta, tono e icono.
 *
 * Lo usa también el Resumen (`resumen/_components/tu-dia.tsx`): las dos
 * superficies enseñan las mismas cinco clases de compromiso, y con dos mapas de
 * iconos distintos la misma fila se leía de dos maneras según por dónde
 * entraras. Un solo vocabulario, dos pantallas.
 */

import {
  Bell,
  Briefcase,
  CalendarClock,
  CornerDownRight,
  RefreshCcw,
  SquareCheck,
  type LucideIcon,
} from "lucide-react";
import type { AgendaKind, PipelineAgendaItem } from "@/hooks/use-pursuits";

/**
 * Rejilla de la tabla — solo a partir de `md`. Por debajo, ficha en columna.
 *
 * La primera columna lleva el aviso **y** el día («5 d» encima de «jue 15
 * oct»): 88 px es lo que pide «hoy 14:00». La última son 184 px porque la fila
 * de plazo pasado lleva dos acciones («No nos presentamos» y abrir la ficha);
 * la que más pedía antes era «Preparar renovación», a 150.
 */
export const GRID = "md:grid-cols-[88px_26px_minmax(0,1fr)_96px_184px] md:gap-3 md:px-3.5";

/** Tramo en el que la API coloca la fila (`banda`), o su urgencia si no lo dice. */
export type AgendaBanda = NonNullable<PipelineAgendaItem["banda"]>;

/**
 * El tramo de la fila. `banda` es opcional en el contrato: una API anterior al
 * campo no lo manda, y ahí la fila cae en su urgencia, que es donde estaba.
 */
export function bandaDe(item: PipelineAgendaItem): AgendaBanda {
  return item.banda ?? item.urgencia;
}

/**
 * Los tramos, en el orden en que la API ordena la lista: primero lo que aún se
 * puede hacer, después lo que hay que cerrar, después el horizonte y al final
 * lo que solo queda esperar o no tiene fecha.
 *
 * `hint` solo lo llevan los dos tramos que no son un plazo por delante: sin esa
 * línea, «Plazo pasado» parecía otro nombre para «Vencidas».
 */
export const BANDAS: { key: AgendaBanda; label: string; tone: string; hint?: string }[] = [
  { key: "vencida", label: "Vencidas", tone: "text-destructive" },
  { key: "hoy", label: "Hoy", tone: "text-destructive" },
  { key: "semana", label: "Próximos 7 días", tone: "text-warning" },
  {
    key: "plazo_pasado",
    label: "Plazo pasado",
    tone: "text-foreground/80",
    hint: "El plazo de presentación pasó y siguen abiertas. Retíralas si no hubo oferta, o registra la presentación en su ficha.",
  },
  { key: "mes", label: "Próximos 30 días", tone: "text-muted-foreground" },
  { key: "despues", label: "Más adelante", tone: "text-muted-foreground" },
  {
    key: "en_resolucion",
    label: "Presentadas, a la espera",
    tone: "text-muted-foreground",
    hint: "La oferta está entregada. Registra el resultado en la ficha cuando se adjudique.",
  },
  { key: "sin_fecha", label: "Sin fecha", tone: "text-muted-foreground" },
];

const CHIP_AMBAR = "bg-warning/10 text-warning";
const CHIP_NEUTRO = "bg-muted-foreground/10 text-muted-foreground";

const CHIP_POR_BANDA: Record<AgendaBanda, string> = {
  vencida: "bg-destructive/10 text-destructive",
  hoy: "bg-destructive/10 text-destructive",
  semana: CHIP_AMBAR,
  // Ni rojo ni ámbar: ya no hay nada que llegue tarde, hay algo que cerrar.
  plazo_pasado: "bg-secondary text-foreground/80",
  mes: "bg-secondary text-foreground/80",
  despues: CHIP_NEUTRO,
  en_resolucion: CHIP_NEUTRO,
  sin_fecha: CHIP_NEUTRO,
};

/** Una ventana de relicitación que ya empezó: está abierta, no llega tarde. */
export function esVentanaAbierta(item: PipelineAgendaItem): boolean {
  return item.due_kind === "relicitacion" && item.dias_restantes != null && item.dias_restantes < 0;
}

/** Color del aviso de la fila. */
export function claseChip(item: PipelineAgendaItem): string {
  if (esVentanaAbierta(item)) return CHIP_AMBAR;
  return CHIP_POR_BANDA[bandaDe(item)];
}

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

/** Un contador de la franja, que además filtra la lista (`item.cuenta_en`). */
export type AgendaContador = NonNullable<PipelineAgendaItem["cuenta_en"]>[number];

/**
 * Los contadores, en el orden de la franja. Qué fila cuenta en cada uno lo
 * decide la API; aquí va el rótulo y el tono de la cifra cuando no es cero.
 */
export const CONTADORES: {
  key: AgendaContador;
  label: string;
  tono?: "destructive" | "warning";
}[] = [
  { key: "plazo_semana", label: "Plazos en 7 días", tono: "destructive" },
  { key: "accion_vencida", label: "Acciones hoy o vencidas", tono: "destructive" },
  { key: "go_no_go", label: "Go/No-Go pendientes" },
  { key: "sin_paso", label: "Sin próxima acción", tono: "warning" },
  { key: "plazo_pasado", label: "Plazo pasado", tono: "warning" },
];

export function esContador(valor: string | null): valor is AgendaContador {
  return CONTADORES.some((contador) => contador.key === valor);
}

/**
 * El contrato tiene dos iconos: `Briefcase` cuando lo que vence es el contrato
 * y `RefreshCcw` cuando lo que se abre es su ventana de relicitación — es otra
 * cosa la que hay que hacer, y el icono lo dice antes que el texto.
 *
 * `anidada` es la tarea que va justo debajo de su oportunidad: la flecha dice
 * de quién es sin repetir el título.
 */
export type IconoAgenda = AgendaKind | "relicitacion" | "anidada";

/**
 * Tabla y no función que devuelva el componente: el compilador de React prohíbe
 * *crear* un componente durante el render (`react-hooks/static-components`), y
 * una llamada que retorna uno cuenta como tal. Con la tabla, el sitio de uso
 * hace `ICONOS[claseDeIcono(item)]` — una lectura, no una creación.
 */
export const ICONOS: Record<IconoAgenda, LucideIcon> = {
  pursuit: CalendarClock,
  tarea: SquareCheck,
  anidada: CornerDownRight,
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
 * Identidad de una fila. Lleva `tarea_id` porque una oportunidad y sus tareas
 * comparten `licitacion_id`: sin él, React reutilizaba el nodo de la primera
 * tarea para la segunda y el inspector se quedaba con el detalle anterior.
 */
export function claveDe(item: PipelineAgendaItem): string {
  return `${item.kind}:${item.licitacion_id}:${item.tarea_id ?? ""}`;
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

/**
 * Los atajos, con lo que tiene que haber delante para que hagan algo. La barra
 * anunciaba los cinco siempre: en Compromisos, sin tareas ni señales, tres de
 * ellos eran teclas muertas.
 */
const SHORTCUTS: { key: string; label: string; aplica?: (item: PipelineAgendaItem) => boolean }[] = [
  { key: "J K", label: "navegar" },
  { key: "S", label: "seguir", aplica: (item) => item.kind === "senal" || item.kind === "renovacion" },
  { key: "X", label: "descartar", aplica: (item) => item.kind === "senal" },
  { key: "C", label: "completar tarea", aplica: (item) => item.kind === "tarea" },
  { key: "⏎", label: "abrir" },
];

/** Los atajos que hacen algo con las filas que se están viendo. */
export function atajosPara(items: readonly PipelineAgendaItem[]): { key: string; label: string }[] {
  return SHORTCUTS.filter((atajo) => !atajo.aplica || items.some(atajo.aplica));
}

/**
 * Qué filas de un tramo van pegadas a su oportunidad: las tareas que siguen,
 * sin nada en medio, a la fila de su oportunidad. La API las ordena juntas
 * (`_ordenar_agenda`); aquí solo se mira si lo están.
 *
 * Hace falta la fila de la oportunidad **encima**: dos tareas seguidas de una
 * oportunidad que está en otro tramo —o filtrada fuera— no tienen a qué
 * referirse con «de esta oportunidad», y conservan su línea entera.
 */
export function tareasAnidadas(filas: readonly PipelineAgendaItem[]): boolean[] {
  let cabeza: number | null = null;
  return filas.map((item) => {
    const anidada = item.kind === "tarea" && item.pursuit_id != null && item.pursuit_id === cabeza;
    if (item.kind === "pursuit") cabeza = item.pursuit_id ?? null;
    else if (!anidada) cabeza = null;
    return anidada;
  });
}
