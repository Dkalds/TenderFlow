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
 * Bandas del Radar como umbral mínimo. El texto explica lo que el nombre de la
 * banda no dice: elegir una acota además al universo puntuable —abiertas y en
 * plazo—, que es el conjunto sobre el que el Radar calcula esa banda.
 */
export const BANDA_OPTIONS: { value: string; label: string }[] = [
  { value: "__any__", label: "— Cualquiera —" },
  { value: "Tibia", label: "Tibia o mejor" },
  { value: "Atractiva", label: "Atractiva o mejor" },
  { value: "Caliente", label: "Solo Caliente" },
];

/**
 * Procedimientos y tipos de contrato que persiste la ingesta (revisión `v85`).
 * No salen de `/meta/filters` —ese catálogo solo publica estado, CCAA,
 * tecnología y CPV— así que aquí son las etiquetas del selector, no datos
 * derivados: el filtro real lo aplica el backend contra la columna.
 */
export const PROCEDIMIENTO_OPTIONS = ["abierto", "restringido", "negociado", "menor"];

export const TIPO_CONTRATO_OPTIONS = ["servicios", "suministros", "obras"];

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
    tecnologia: rule.tecnologia ?? "",
    organo: rule.organo ?? "",
    procedimiento: rule.procedimiento ?? "",
    tipoContrato: rule.tipo_contrato ?? "",
    bandaMin: rule.banda_min ?? "",
    plazoMinDias: rule.plazo_min_dias != null ? String(rule.plazo_min_dias) : "",
  };
}

/**
 * ¿La regla filtra algo? Antes bastaba con exigir palabra clave, porque era el
 * único criterio de texto. Con los de S4.4 una regla legítima puede no tener
 * ninguna («todo lo de este órgano», «todo lo Caliente en Madrid»), así que la
 * condición pasa a ser «al menos un criterio»: guardar una regla vacía
 * notificaría el mercado entero.
 */
export function tieneCriterio(form: RuleFormState): boolean {
  return Boolean(
    form.keyword.trim() ||
      form.cpv.trim() ||
      form.minImporte.trim() ||
      form.ccaa ||
      form.tecnologia ||
      form.organo.trim() ||
      form.procedimiento ||
      form.tipoContrato ||
      form.bandaMin ||
      form.plazoMinDias.trim(),
  );
}

/** Entero del formulario, o `null` si está vacío o no es un número usable. */
function enteroONulo(value: string): number | null {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

/** Los seis criterios de S4.4 tal y como los espera el contrato. */
function criteriosDeFormulario(form: RuleFormState): RuleCriteriosS4 {
  return {
    tecnologia: form.tecnologia || null,
    organo: form.organo.trim() || null,
    procedimiento: form.procedimiento || null,
    tipo_contrato: form.tipoContrato || null,
    banda_min: (form.bandaMin || null) as Banda | null,
    plazo_min_dias: enteroONulo(form.plazoMinDias),
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
    nombre: form.keyword.trim() || form.organo.trim() || form.tecnologia || null,
    keyword: form.keyword.trim() || null,
    cpv: form.cpv.trim() || null,
    min_importe: form.minImporte ? parseFloat(form.minImporte) : null,
    ccaa: form.ccaa || null,
    frequency: form.frequency,
    active,
    ...criteriosDeFormulario(form),
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
    // Los criterios de S4.4 viajan en CADA cuerpo: un PUT que los omitiera los
    // borraría, y el sitio donde eso pasa es el switch de activar/pausar, que
    // manda la regla entera con un `active` distinto.
    tecnologia: rule.tecnologia ?? null,
    organo: rule.organo ?? null,
    procedimiento: rule.procedimiento ?? null,
    tipo_contrato: rule.tipo_contrato ?? null,
    banda_min: rule.banda_min ?? null,
    plazo_min_dias: rule.plazo_min_dias ?? null,
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
    // El ámbito global también trae tecnología: llega con el mismo nombre que
    // usa el resto de la consola, así que se prefija igual que la CCAA.
    tecnologia: prefill?.tecnologia?.split(",")[0] ?? "",
    organo: "",
    procedimiento: "",
    tipoContrato: "",
    bandaMin: "",
    plazoMinDias: "",
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
