/**
 * Reglas de watchlist: traducciones de formulario, migración del legacy y
 * deduplicado de coincidencias, fuera del árbol de render.
 *
 * `mi-watchlist/page.tsx` pasa de las 1.000 líneas. Lo que de verdad puede
 * romperse sin que la UI se queje no es el marcado: es que el formulario mande
 * `""` donde el contrato pide `null`, que la migración del `localStorage` dé por
 * buena una subida que falló (y borre reglas del usuario), o que el listado
 * combinado repita la misma licitación una vez por regla activa. Eso vive aquí.
 *
 * Sin fetch propio: la migración recibe el `POST` inyectado, así que el test la
 * ejercita sin servidor y sin montar la página.
 */
"use client";

import { useEffect, useRef } from "react";
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

export const FREQ_OPTIONS: { value: Frequency; label: string }[] = [
  { value: "immediate", label: "Inmediata" },
  { value: "daily", label: "Diaria" },
  { value: "weekly", label: "Semanal" },
];

export const FREQ_LABEL: Record<Frequency, string> = {
  immediate: "Inmediata",
  daily: "Diaria",
  weekly: "Semanal",
};

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

/* ── Migración one-shot del localStorage ────────────────────────────── */

export interface LegacyRule {
  keyword?: string;
  cpvFilter?: string;
  minImporte?: number | null;
  ccaa?: string;
  frequency?: "inmediata" | "diaria" | "semanal";
  active?: boolean;
}

export const LEGACY_KEY = "watchlist_rules";
export const MIGRATED_FLAG = "watchlist_rules_migrated";

const LEGACY_FREQ: Record<string, Frequency> = {
  inmediata: "immediate",
  diaria: "daily",
  semanal: "weekly",
};

export function legacyToBody(r: LegacyRule): RuleBody {
  return {
    nombre: r.keyword?.trim() || null,
    keyword: r.keyword?.trim() || null,
    cpv: r.cpvFilter?.trim() || null,
    min_importe: r.minImporte ?? null,
    ccaa: r.ccaa || null,
    frequency: LEGACY_FREQ[r.frequency ?? "diaria"] ?? "daily",
    active: r.active ?? true,
  };
}

/**
 * Sube las reglas del `localStorage` legacy al servidor.
 *
 * Best-effort por regla: si una falla se siguen intentando las demás, pero el
 * resultado es `false` y **el llamador no debe marcar la migración como
 * completa ni vaciar el legacy**. Antes se borraban aunque el POST devolviera
 * 403 y el usuario perdía sus reglas sin enterarse; así el próximo arranque
 * reintenta lo pendiente.
 */
export async function migrateLegacyRules(
  legacy: LegacyRule[],
  post: (body: RuleBody) => Promise<unknown>,
): Promise<boolean> {
  let todasOk = true;
  for (const r of legacy) {
    try {
      await post(legacyToBody(r));
    } catch {
      todasOk = false;
    }
  }
  return todasOk;
}

export interface LegacyMigrationDeps {
  /** Lectura del flag/lista del `localStorage` (inyectada para el test). */
  readFlag: () => boolean;
  readLegacy: () => LegacyRule[];
  markMigrated: () => void;
  clearLegacy: () => void;
  post: (body: RuleBody) => Promise<unknown>;
  onDone: () => void;
}

/**
 * Ejecuta la migración una sola vez por montaje.
 *
 * El `ref` la protege del doble montaje de StrictMode: sin él la primera
 * ejecución duplicaba cada regla del usuario.
 */
export function useLegacyRuleMigration(deps: LegacyMigrationDeps): void {
  const migratedRef = useRef(false);
  // Se congelan las dependencias del primer render: la migración corre una sola
  // vez al montar, así que re-leerlas en cada render no cambiaría nada y sí
  // obligaría a escribir el ref durante el render.
  const depsRef = useRef(deps);

  useEffect(() => {
    if (migratedRef.current) return;
    migratedRef.current = true;
    const d = depsRef.current;
    if (d.readFlag()) return;
    const legacy = d.readLegacy();
    if (legacy.length === 0) {
      d.markMigrated();
      return;
    }
    void (async () => {
      const todasOk = await migrateLegacyRules(legacy, d.post);
      if (todasOk) {
        d.markMigrated();
        d.clearLegacy();
      }
      d.onDone();
    })();
  }, []);
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
