/**
 * Etiquetado de la ficha de un webhook: formato de plantilla y fechas.
 *
 * Lo comparten la tarjeta de cada webhook y el formulario de alta, así que no
 * puede vivir en ninguno de los dos.
 */

import { formatDateTime } from "@/lib/utils";

const EMPTY = "—";

/**
 * Formatos de plantilla (D13). El backend los sirve en
 * `GET /webhooks/event-types` junto a los tipos; esta lista es solo el
 * ETIQUETADO en castellano, que no es dato sino copy — el valor válido lo
 * sigue decidiendo el backend.
 */
export const FORMATO_LABEL: Record<string, string> = {
  json: "JSON (genérico)",
  slack_blocks: "Slack · Block Kit",
  teams_adaptive_card: "Teams · Adaptive Card",
};

/** Formatos que el selector de alta ofrece, en el orden en que se enseñan. */
export const FORMATO_VALUES = ["json", "slack_blocks", "teams_adaptive_card"] as const;

export type FormatoWebhook = (typeof FORMATO_VALUES)[number];

/** Fecha de una entrega; `—` si no hay ninguna todavía o si viene ilegible. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return EMPTY;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? EMPTY : formatDateTime(date);
}

/** ¿Es `value` uno de los formatos que el backend acepta? */
export function esFormatoConocido(value: string): value is FormatoWebhook {
  return (FORMATO_VALUES as readonly string[]).includes(value);
}
