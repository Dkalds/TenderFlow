/**
 * Reglas de watchlist: traducciones de formulario y deduplicado de
 * coincidencias, fuera del árbol de render.
 *
 * `mi-watchlist/page.tsx` pasaba de las 950 líneas. Lo que de verdad puede
 * romperse sin que la UI se queje no es el marcado: es que el formulario mande
 * `""` donde el contrato pide `null`, o que el listado combinado repita la
 * misma licitación una vez por regla activa. Eso vive aquí.
 *
 * La migración del `localStorage` legacy se mudó a
 * `use-legacy-rule-migration.ts`: es el único de los tres asuntos que puede
 * borrar datos del usuario y merece leerse aislado.
 */
"use client";

import type { WatchlistRuleMatch, WatchlistRuleOut } from "@/lib/api-types";

export type Frequency = "immediate" | "daily" | "weekly";

export type ApiRule = WatchlistRuleOut;
export type MatchItem = WatchlistRuleMatch;

export interface RuleBody {
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
}

/* ── Opciones de formulario ─────────────────────────────────────────── */

export const CCAA_FALLBACK = [
  "__all__",
  "Andalucia",
  "Aragon",
  "Asturias",
  "Baleares",
  "Canarias",
  "Cantabria",
  "Castilla y Leon",
  "Castilla-La Mancha",
  "Cataluna",
  "Ceuta",
  "Comunidad Valenciana",
  "Extremadura",
  "Galicia",
  "La Rioja",
  "Madrid",
  "Melilla",
  "Murcia",
  "Navarra",
  "Pais Vasco",
];

/**
 * Etiquetas del selector de frecuencia.
 *
 * `immediate` NO es inmediata y llamarla así prometía una actualidad que la
 * ingesta no da: el job de alertas entrega en el siguiente run de digests y ese
 * cron corre cada 4 horas (`scheduler/watchlist_rules_alerts.py`), así que el
 * peor caso son ~4 h. El proyecto ya retiró «tiempo real» del login por esta
 * misma razón; el valor del contrato se queda como está y solo cambia lo que
 * lee el usuario.
 */
export const FREQ_LABEL: Record<Frequency, string> = {
  immediate: "En cuanto se detecte (hasta ~4 h)",
  daily: "Diaria",
  weekly: "Semanal",
};

export const FREQ_OPTIONS: { value: Frequency; label: string }[] = [
  { value: "immediate", label: FREQ_LABEL.immediate },
  { value: "daily", label: FREQ_LABEL.daily },
  { value: "weekly", label: FREQ_LABEL.weekly },
];

/**
 * Nota bajo el selector: la latencia es de la ingesta, no de la frecuencia
 * elegida, y para un plazo que vence hoy ninguna frecuencia es suficiente.
 */
export const FREQ_NOTE =
  "TenderFlow revisa las fuentes cada 4 horas: ninguna frecuencia entrega antes. Para un plazo que vence hoy, la fuente oficial sigue siendo el perfil del contratante.";

/* ── Conteo de coincidencias ────────────────────────────────────────── */

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
 * Lista de CCAA del selector: las de `meta/filters` si llegaron, y si no el
 * fallback local. La opción «— Todas —` (`__all__`) va siempre delante.
 */
export function ccaaOptions(metaCcaas: string[] | undefined): string[] {
  return metaCcaas && metaCcaas.length > 0 ? ["__all__", ...metaCcaas] : CCAA_FALLBACK;
}

/* ── Formulario ↔ contrato ──────────────────────────────────────────── */

export function ruleToFormState(rule: ApiRule): RuleFormState {
  return {
    keyword: rule.keyword ?? "",
    cpv: rule.cpv ?? "",
    minImporte: rule.min_importe != null ? String(rule.min_importe) : "",
    ccaa: rule.ccaa ?? "",
    frequency: rule.frequency,
  };
}

/**
 * Cuerpo de la petición desde el formulario.
 *
 * Los campos vacíos viajan como `null`, no como `""`: el backend filtra por
 * «campo presente», y un string vacío es un criterio que no casa con nada.
 */
export function formStateToBody(form: RuleFormState, active: boolean): RuleBody {
  return {
    nombre: form.keyword.trim() || null,
    keyword: form.keyword.trim() || null,
    cpv: form.cpv.trim() || null,
    min_importe: form.minImporte ? parseFloat(form.minImporte) : null,
    ccaa: form.ccaa || null,
    frequency: form.frequency,
    active,
  };
}

/** Cuerpo completo de una regla existente, con parches opcionales encima. */
export function ruleToBody(rule: ApiRule, overrides: Partial<RuleBody> = {}): RuleBody {
  return {
    nombre: rule.nombre ?? null,
    keyword: rule.keyword ?? null,
    cpv: rule.cpv ?? null,
    min_importe: rule.min_importe ?? null,
    ccaa: rule.ccaa ?? null,
    frequency: rule.frequency ?? "daily",
    active: rule.active ?? true,
    ...overrides,
  };
}

/**
 * Prefill desde la command palette: «Crear regla con estos filtros» navega con
 * `?prefill=<JSON>`. Un JSON roto no puede tumbar la pantalla, así que se
 * ignora en silencio.
 */
export function parsePrefill(raw: string | null): Record<string, string> | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Record<string, string>;
  } catch {
    return null;
  }
}

/** Estado inicial del formulario «Nueva regla» a partir del prefill. */
export function prefillToFormState(
  prefill: Record<string, string> | null,
): RuleFormState {
  return {
    keyword: prefill?.q ?? "",
    cpv: "",
    minImporte: prefill?.importe_min ?? "",
    // El ámbito global admite varias CCAA; el formulario solo una.
    ccaa: prefill?.ccaa?.split(",")[0] ?? "",
    frequency: "daily",
  };
}

/* ── Resultados combinados ──────────────────────────────────────────── */

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
