/**
 * Tests de la lógica de reglas de watchlist (`_hooks/use-watchlist-rules.ts`).
 *
 * `page.test.tsx` cubre el marcado; aquí van las reglas que el marcado no
 * enseña: que el formulario mande `null` donde el contrato pide `null` y que el
 * listado combinado no repita una licitación capturada por dos reglas a la vez.
 *
 * La migración del `localStorage` se probaba también aquí; vive ahora en
 * `use-legacy-rule-migration.test.tsx`, junto al módulo que se le separó.
 */
import { describe, it, expect } from "vitest";
import {
  CCAA_FALLBACK,
  FREQ_LABEL,
  FREQ_OPTIONS,
  activeRulesOf,
  ccaaOptions,
  dedupeMatches,
  formStateToBody,
  parsePrefill,
  prefillToFormState,
  ruleToBody,
  ruleToFormState,
  type ApiRule,
  type MatchItem,
  type RuleFormState,
} from "../_hooks/use-watchlist-rules";

/* ── Fixtures ───────────────────────────────────────────────────────── */

function rule(over: Partial<ApiRule> & { id: number }): ApiRule {
  return {
    nombre: "SAP",
    keyword: "SAP",
    cpv: "72000000",
    min_importe: 50000,
    ccaa: "Madrid",
    frequency: "daily",
    active: true,
    ...over,
  } as ApiRule;
}

const EMPTY_FORM: RuleFormState = {
  keyword: "",
  cpv: "",
  minImporte: "",
  ccaa: "",
  frequency: "daily",
};

/* ── Formulario ↔ contrato ──────────────────────────────────────────── */

describe("ruleToFormState", () => {
  it("convierte los nulos del contrato en cadenas vacías del formulario", () => {
    const form = ruleToFormState(
      rule({ id: 1, keyword: null, cpv: null, min_importe: null, ccaa: null }),
    );
    expect(form).toEqual({
      keyword: "",
      cpv: "",
      minImporte: "",
      ccaa: "",
      frequency: "daily",
    });
  });

  it("el importe mínimo viaja como texto al input numérico", () => {
    expect(ruleToFormState(rule({ id: 1, min_importe: 50000 })).minImporte).toBe("50000");
  });

  it("un importe mínimo de cero no se confunde con «sin importe»", () => {
    // `min_importe: 0` es un criterio válido; tratarlo como ausente lo perdería
    // al reabrir el panel de edición.
    expect(ruleToFormState(rule({ id: 1, min_importe: 0 })).minImporte).toBe("0");
  });
});

describe("formStateToBody", () => {
  it("los campos vacíos viajan como null, no como cadena vacía", () => {
    // El backend filtra por «campo presente»: `""` sería un criterio que no casa
    // con nada y dejaría la regla muda.
    expect(formStateToBody(EMPTY_FORM, true)).toEqual({
      nombre: null,
      keyword: null,
      cpv: null,
      min_importe: null,
      ccaa: null,
      frequency: "daily",
      active: true,
    });
  });

  it("recorta los espacios de keyword y cpv", () => {
    const body = formStateToBody(
      { ...EMPTY_FORM, keyword: "  SAP  ", cpv: " 72000000 " },
      true,
    );
    expect(body.keyword).toBe("SAP");
    expect(body.cpv).toBe("72000000");
  });

  it("una keyword de solo espacios cuenta como ausente", () => {
    expect(formStateToBody({ ...EMPTY_FORM, keyword: "   " }, true).keyword).toBeNull();
  });

  it("el nombre por defecto es la keyword", () => {
    const body = formStateToBody({ ...EMPTY_FORM, keyword: "SAP" }, true);
    expect(body.nombre).toBe("SAP");
  });

  it("el importe mínimo se manda como número", () => {
    const body = formStateToBody({ ...EMPTY_FORM, minImporte: "1500.5" }, true);
    expect(body.min_importe).toBe(1500.5);
  });

  it("propaga el estado activo recibido", () => {
    expect(formStateToBody(EMPTY_FORM, false).active).toBe(false);
  });
});

describe("ruleToBody", () => {
  it("reconstruye el cuerpo completo de una regla existente", () => {
    expect(ruleToBody(rule({ id: 9 }))).toEqual({
      nombre: "SAP",
      keyword: "SAP",
      cpv: "72000000",
      min_importe: 50000,
      ccaa: "Madrid",
      frequency: "daily",
      active: true,
    });
  });

  it("los parches pisan al valor de la regla — es el toggle de activar", () => {
    expect(ruleToBody(rule({ id: 9 }), { active: false }).active).toBe(false);
  });

  it("rellena los defaults que el contrato deja opcionales", () => {
    const parcial = { id: 3 } as ApiRule;
    const body = ruleToBody(parcial);
    expect(body.frequency).toBe("daily");
    expect(body.active).toBe(true);
    expect(body.keyword).toBeNull();
  });
});

/* ── Prefill desde la command palette ───────────────────────────────── */

describe("parsePrefill", () => {
  it("null sin parámetro", () => {
    expect(parsePrefill(null)).toBeNull();
    expect(parsePrefill("")).toBeNull();
  });

  it("decodifica el JSON de filtros", () => {
    expect(parsePrefill('{"q":"SAP","ccaa":"Madrid"}')).toEqual({
      q: "SAP",
      ccaa: "Madrid",
    });
  });

  it("un JSON roto no tumba la pantalla", () => {
    expect(parsePrefill("{no-es-json")).toBeNull();
  });
});

describe("prefillToFormState", () => {
  it("formulario vacío sin prefill", () => {
    expect(prefillToFormState(null)).toEqual(EMPTY_FORM);
  });

  it("traslada búsqueda e importe mínimo del ámbito", () => {
    const form = prefillToFormState({ q: "SAP", importe_min: "100000" });
    expect(form.keyword).toBe("SAP");
    expect(form.minImporte).toBe("100000");
  });

  it("de varias CCAA del ámbito el formulario se queda con la primera", () => {
    // El ámbito global admite lista; el formulario de regla solo una.
    expect(prefillToFormState({ ccaa: "Madrid,Galicia" }).ccaa).toBe("Madrid");
  });

  it("ignora las claves del ámbito que la regla no tiene", () => {
    expect(prefillToFormState({ estado: "PUB", tecnologia: "IA" })).toEqual(EMPTY_FORM);
  });
});

/* ── Opciones de CCAA ───────────────────────────────────────────────── */

describe("ccaaOptions", () => {
  it("cae al fallback local cuando meta no responde", () => {
    expect(ccaaOptions(undefined)).toBe(CCAA_FALLBACK);
    expect(ccaaOptions([])).toBe(CCAA_FALLBACK);
  });

  it("usa las del servidor con «— Todas —» delante", () => {
    expect(ccaaOptions(["Madrid", "Galicia"])).toEqual([
      "__all__",
      "Madrid",
      "Galicia",
    ]);
  });

  it("el fallback ya trae la opción «todas»", () => {
    expect(CCAA_FALLBACK[0]).toBe("__all__");
  });
});

describe("opciones de frecuencia", () => {
  it("las tres del contrato, con etiqueta para cada una", () => {
    expect(FREQ_OPTIONS.map((f) => f.value)).toEqual(["immediate", "daily", "weekly"]);
    for (const { value, label } of FREQ_OPTIONS) {
      expect(FREQ_LABEL[value]).toBe(label);
    }
  });
});

/* ── Reglas activas y coincidencias combinadas ──────────────────────── */

describe("activeRulesOf", () => {
  it("lista vacía mientras las reglas no han cargado", () => {
    expect(activeRulesOf(undefined)).toEqual([]);
  });

  it("descarta las desactivadas", () => {
    const activas = activeRulesOf([
      rule({ id: 1, active: true }),
      rule({ id: 2, active: false }),
    ]);
    expect(activas.map((r) => r.id)).toEqual([1]);
  });
});

describe("dedupeMatches", () => {
  // El contrato declara `id_externo` obligatorio, pero el deduplicado mantiene
  // la cadena de fallbacks por si una fuente lo omite: es ese camino defensivo
  // el que se ejercita aquí, de ahí el cast.
  const match = (over: Record<string, unknown>) => over as unknown as MatchItem;

  it("una licitación capturada por dos reglas aparece una vez", () => {
    const result = dedupeMatches([
      [match({ id_externo: "X1", titulo: "Obras" })],
      [match({ id_externo: "X1", titulo: "Obras" })],
    ]);
    expect(result).toHaveLength(1);
  });

  it("conserva la primera coincidencia, no la última", () => {
    const result = dedupeMatches([
      [match({ id_externo: "X1", titulo: "Primera" })],
      [match({ id_externo: "X1", titulo: "Segunda" })],
    ]);
    expect(result[0].titulo).toBe("Primera");
  });

  it("sin id_externo deduplica por título", () => {
    const result = dedupeMatches([
      [match({ id_externo: null, titulo: "Obras" })],
      [match({ id_externo: null, titulo: "Obras" })],
      [match({ id_externo: null, titulo: "Otra" })],
    ]);
    expect(result).toHaveLength(2);
  });

  it("sin id ni título no fusiona elementos distintos", () => {
    const result = dedupeMatches([
      [match({ id_externo: null, titulo: null, importe: 1 })],
      [match({ id_externo: null, titulo: null, importe: 2 })],
    ]);
    expect(result).toHaveLength(2);
  });

  it("mantiene el orden de llegada de las reglas", () => {
    const result = dedupeMatches([
      [match({ id_externo: "A" }), match({ id_externo: "B" })],
      [match({ id_externo: "C" })],
    ]);
    expect(result.map((m) => m.id_externo)).toEqual(["A", "B", "C"]);
  });

  it("vacío sin reglas activas", () => {
    expect(dedupeMatches([])).toEqual([]);
    expect(dedupeMatches([[], []])).toEqual([]);
  });
});
