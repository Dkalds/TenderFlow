/**
 * Traducción entre el formulario de la pantalla y el contrato de la API de
 * reglas, fuera del árbol de render.
 *
 * `mi-watchlist/page.tsx` pasaba de las 950 líneas. Lo que de verdad puede
 * romperse sin que la UI se queje no es el marcado: es que el formulario mande
 * `""` donde el contrato pide `null`. Eso vive aquí.
 *
 * El módulo se quedó otra vez sobre el techo de 300 líneas al añadir S4.4 sus
 * seis criterios, así que lo que no era traducción se ha ido a su propio
 * fichero: las formas a `watchlist-rule-types.ts`, los catálogos de los
 * selectores a `watchlist-rule-options.ts`, el deduplicado y el conteo de
 * coincidencias a `watchlist-matches.ts` y la migración del `localStorage`
 * legacy a `use-legacy-rule-migration.ts` (esta última es la única que puede
 * borrar datos del usuario y merece leerse aislada).
 */
"use client";

import type {
  ApiRule,
  Banda,
  RuleBody,
  RuleCriteriosS4,
  RuleFormState,
} from "./watchlist-rule-types";

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
