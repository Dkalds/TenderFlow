/**
 * Coincidencias de las reglas: qué reglas se consultan, cómo se combinan sin
 * repetir licitaciones y cómo se lee un conteo que viene saturado.
 *
 * Es el asunto que `use-watchlist-rules.ts` tenía pegado al de traducir el
 * formulario sin compartir nada con él: aquí no hay formulario, solo el
 * resultado que devuelve el servidor.
 */

import type { ApiRule, MatchItem } from "./watchlist-rule-types";

/**
 * Techo del conteo que devuelve el listado (`match_count`), en espejo de
 * `MATCH_COUNT_CAP` en `db/repositories/watchlist_rules.py`. El backend cuenta
 * sobre un subselect con `LIMIT` para no barrer 1,6M filas por regla, así que
 * al llegar al tope el número solo significa «al menos tantas».
 */
export const MATCH_COUNT_CAP = 1000;

/** Texto del badge: «999+» cuando el conteo viene saturado. */
export function formatMatchCount(count: number): string {
  return count >= MATCH_COUNT_CAP ? "999+" : String(count);
}

/**
 * Une las coincidencias de todas las reglas activas sin repetir licitaciones.
 *
 * Dos reglas del mismo usuario suelen solapar («SAP» y «SAP Madrid»); sin
 * deduplicar, el listado enseñaría la misma licitación tantas veces como reglas
 * la capturen. Se prefiere `id_externo`; si falta se cae al título y, en última
 * instancia, al objeto serializado, para no fusionar dos cosas distintas.
 */
export function dedupeMatches(perRule: MatchItem[][]): MatchItem[] {
  const seen = new Map<string, MatchItem>();
  for (const items of perRule) {
    for (const item of items) {
      const key = item.id_externo ?? item.titulo ?? JSON.stringify(item);
      if (!seen.has(key)) seen.set(key, item);
    }
  }
  return Array.from(seen.values());
}

/** Reglas activas — las únicas cuyas coincidencias se piden al servidor. */
export function activeRulesOf(rules: ApiRule[] | undefined): ApiRule[] {
  return (rules ?? []).filter((r) => r.active);
}
