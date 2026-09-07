/**
 * Formas que se cruzan entre la API de reglas y el formulario de la pantalla.
 *
 * Están aparte de `use-watchlist-rules.ts` porque las importa casi todo
 * `mi-watchlist/` —las seis piezas de `_components/` y los tres hooks—, mientras
 * que las funciones de traducción solo las usan dos. Tenerlas en el mismo
 * módulo obligaba a arrastrar el fichero entero (y su techo de 300 líneas) a
 * cualquier componente que solo necesitara nombrar un tipo.
 */

import type { WatchlistRuleMatch, WatchlistRuleOut } from "@/lib/api-types";

export type Frequency = "immediate" | "daily" | "weekly";

/** Banda comercial del Radar, de menor a mayor exigencia. */
export type Banda = "Descarte" | "Tibia" | "Atractiva" | "Caliente";

/**
 * Criterios de S4.4 que la API ya acepta y devuelve, y que el cliente generado
 * todavía no describe (`npm run codegen:file` los incorpora al regenerar desde
 * el OpenAPI de esta rama).
 *
 * Se declaran opcionales encima de `WatchlistRuleOut` en vez de re-teclear el
 * DTO entero: la pantalla compila con el cliente viejo y con el nuevo, y no se
 * duplica la forma del contrato — que es el anti-patrón que ADR-014 prohíbe.
 */
export interface RuleCriteriosS4 {
  tecnologia: string | null;
  organo: string | null;
  procedimiento: string | null;
  tipo_contrato: string | null;
  banda_min: Banda | null;
  plazo_min_dias: number | null;
}

export type ApiRule = WatchlistRuleOut & Partial<RuleCriteriosS4>;
export type MatchItem = WatchlistRuleMatch;

export interface RuleBody extends RuleCriteriosS4 {
  nombre: string | null;
  keyword: string | null;
  cpv: string | null;
  min_importe: number | null;
  ccaa: string | null;
  frequency: Frequency;
  active: boolean;
}

/** Estado de formulario compartido entre «Nueva regla» y el panel de edición. */
export interface RuleFormState {
  keyword: string;
  cpv: string;
  minImporte: string;
  ccaa: string;
  frequency: Frequency;
  tecnologia: string;
  organo: string;
  procedimiento: string;
  tipoContrato: string;
  bandaMin: string;
  plazoMinDias: string;
}
