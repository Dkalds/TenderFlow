/**
 * Vocabulario visual de la agenda: las bandas de urgencia que manda el backend,
 * su color, y cómo se resume cada compromiso en una línea.
 *
 * Ninguna de estas tablas decide *en qué banda cae* un ítem — eso viene en
 * `item.urgencia` desde `GET /pursuits/agenda` (ADR-014). Aquí solo se traduce
 * a etiqueta y tono.
 */

import { Bell, Briefcase, CalendarClock } from "lucide-react";
import { EMPTY, truncate } from "@/lib/utils";
import type { AgendaUrgencia, PipelineAgendaItem } from "@/hooks/use-pursuits";

/** Rejilla de la tabla — solo a partir de `md`. Por debajo, ficha en columna. */
export const GRID = "md:grid-cols-[72px_26px_1fr_110px_96px] md:gap-3 md:px-3.5";

export const BANDAS: { key: AgendaUrgencia; label: string; tone: string }[] = [
  { key: "vencida", label: "Vencidas", tone: "text-destructive" },
  { key: "hoy", label: "Hoy", tone: "text-destructive" },
  { key: "semana", label: "Próximos 7 días", tone: "text-amber-600 dark:text-amber-400" },
  { key: "mes", label: "Próximos 30 días", tone: "text-muted-foreground" },
  { key: "despues", label: "Más adelante", tone: "text-muted-foreground" },
  { key: "sin_fecha", label: "Sin fecha", tone: "text-muted-foreground" },
];

export const CHIP_POR_BANDA: Record<AgendaUrgencia, string> = {
  vencida: "bg-destructive/12 text-destructive",
  hoy: "bg-destructive/12 text-destructive",
  semana: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  mes: "bg-secondary text-foreground/80",
  despues: "bg-muted-foreground/10 text-muted-foreground",
  sin_fecha: "bg-muted-foreground/10 text-muted-foreground",
};

export const STATUS_LABELS: Record<string, string> = {
  identified: "Identificada",
  qualifying: "Calificando",
  go_no_go: "Go/No-go",
  preparing: "En preparación",
  submitted: "Presentada",
  won: "Ganada",
  lost: "Perdida",
  withdrawn: "Retirada",
};

export const KIND_META = {
  pursuit: { icon: Briefcase, label: "Pursuit" },
  senal: { icon: Bell, label: "Señal" },
  renovacion: { icon: CalendarClock, label: "Renovación" },
} as const;

export const SHORTCUTS = [
  { key: "J K", label: "navegar" },
  { key: "S", label: "seguir" },
  { key: "X", label: "descartar" },
  { key: "⏎", label: "abrir" },
];

export function plazoChip(item: PipelineAgendaItem): string {
  if (item.dias_restantes == null) return EMPTY;
  if (item.urgencia === "hoy") return "hoy";
  if (item.dias_restantes < 0) return `−${Math.abs(item.dias_restantes)} d`;
  return `${item.dias_restantes} d`;
}

export function metaLinea(item: PipelineAgendaItem): string {
  const partes: string[] = [];
  if (item.kind === "pursuit" && item.status) {
    partes.push(STATUS_LABELS[item.status] ?? item.status);
    if (item.next_action) partes.push(truncate(item.next_action, 44));
  }
  if (item.kind === "senal" && item.rule_nombre) partes.push(`Regla «${item.rule_nombre}»`);
  if (item.kind === "renovacion") {
    partes.push(
      item.adjudicatario ? `Adjudicatario: ${truncate(item.adjudicatario, 36)}` : "Contrato que vence",
    );
  }
  if (item.organo) partes.push(truncate(item.organo, 48));
  return partes.join(" · ");
}
