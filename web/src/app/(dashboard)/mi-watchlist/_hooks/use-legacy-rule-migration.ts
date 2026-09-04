/**
 * Migración one-shot de las reglas que vivían en el `localStorage`.
 *
 * Vivía dentro de `use-watchlist-rules.ts`, que mezclaba tres asuntos sin
 * relación (traducciones de formulario, migración del legacy y deduplicado de
 * coincidencias) en un módulo que ya pasaba el techo de 300 líneas. Se separa
 * el único de los tres que puede **destruir datos del usuario**: conviene que
 * su contrato —qué se marca como migrado y cuándo se vacía el legacy— se lea
 * de un vistazo, sin scroll por el resto del fichero.
 *
 * Sin fetch propio: el `POST` se inyecta, así que el test la ejercita sin
 * servidor y sin montar la página.
 */
"use client";

import { useEffect, useRef } from "react";
import type { Frequency, RuleBody } from "./use-watchlist-rules";

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
