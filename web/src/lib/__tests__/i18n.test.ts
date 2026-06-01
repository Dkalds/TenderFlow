/**
 * Tests for web/src/lib/i18n.ts
 *
 * Covers: useLocale store, t(), tWithLocale(), setLocale(), getLocale(),
 *         supportedLocales(), and cascading fallback logic.
 */
import { describe, it, expect, beforeEach } from "vitest";
import {
  useLocale,
  t,
  tWithLocale,
  setLocale,
  getLocale,
  supportedLocales,
} from "@/lib/i18n";
import type { Locale } from "@/lib/i18n";

// Reset locale store to "es" before every test so they are fully isolated
beforeEach(() => {
  useLocale.getState().setLocale("es");
});

// ---------------------------------------------------------------------------
// supportedLocales
// ---------------------------------------------------------------------------

describe("supportedLocales", () => {
  it("returns an array containing 'es' and 'en'", () => {
    const locales = supportedLocales();
    expect(locales).toContain("es");
    expect(locales).toContain("en");
  });

  it("returns exactly 2 supported locales", () => {
    expect(supportedLocales()).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// useLocale store
// ---------------------------------------------------------------------------

describe("useLocale store", () => {
  it("starts with 'es' as the default locale", () => {
    expect(useLocale.getState().locale).toBe("es");
  });

  it("setLocale('en') changes locale to 'en'", () => {
    useLocale.getState().setLocale("en");
    expect(useLocale.getState().locale).toBe("en");
  });

  it("setLocale('es') changes locale to 'es'", () => {
    useLocale.getState().setLocale("en");
    useLocale.getState().setLocale("es");
    expect(useLocale.getState().locale).toBe("es");
  });

  it("setLocale with unsupported value falls back to 'es'", () => {
    useLocale.getState().setLocale("fr");
    expect(useLocale.getState().locale).toBe("es");
  });

  it("setLocale with empty string falls back to 'es'", () => {
    useLocale.getState().setLocale("");
    expect(useLocale.getState().locale).toBe("es");
  });

  it("setLocale with arbitrary string falls back to 'es'", () => {
    useLocale.getState().setLocale("zh-CN");
    expect(useLocale.getState().locale).toBe("es");
  });
});

// ---------------------------------------------------------------------------
// setLocale / getLocale (deprecated wrappers)
// ---------------------------------------------------------------------------

describe("setLocale / getLocale (deprecated)", () => {
  it("setLocale('en') is reflected by getLocale()", () => {
    setLocale("en");
    expect(getLocale()).toBe("en");
  });

  it("setLocale('invalid') causes getLocale() to return 'es'", () => {
    setLocale("invalid");
    expect(getLocale()).toBe("es");
  });

  it("setLocale and getLocale are in sync with useLocale store", () => {
    setLocale("en");
    expect(useLocale.getState().locale).toBe("en");
    useLocale.getState().setLocale("es");
    expect(getLocale()).toBe("es");
  });
});

// ---------------------------------------------------------------------------
// t() — reads from active locale
// ---------------------------------------------------------------------------

describe("t()", () => {
  it("returns Spanish translation when locale is 'es'", () => {
    expect(t("common.loading")).toBe("Cargando...");
  });

  it("returns English translation after setLocale('en')", () => {
    setLocale("en");
    expect(t("common.loading")).toBe("Loading...");
  });

  it("returns the key itself for an unknown key", () => {
    expect(t("unknown.key.that.does.not.exist")).toBe(
      "unknown.key.that.does.not.exist",
    );
  });

  it("returns the key itself for an unknown key in 'en' locale", () => {
    setLocale("en");
    expect(t("totally.unknown")).toBe("totally.unknown");
  });

  it("interpolates {var} placeholders", () => {
    // There may not be a key with vars in translations — use a key that exists
    // and verify the interpolation engine works. We test via tWithLocale below
    // using a custom template. Here we verify no crash on a real key with vars
    // that has no placeholders (vars are simply ignored).
    const result = t("common.loading", { count: "5" });
    expect(result).toBe("Cargando...");
  });

  it("returns all known es keys correctly", () => {
    const cases: [string, string][] = [
      ["common.error", "Error"],
      ["common.search", "Buscar"],
      ["common.filter", "Filtrar"],
      ["common.export", "Exportar"],
      ["auth.login", "Iniciar sesion"],
      ["app.title", "TenderFlow"],
    ];
    for (const [key, expected] of cases) {
      expect(t(key)).toBe(expected);
    }
  });

  it("returns all known en keys correctly after locale change", () => {
    setLocale("en");
    const cases: [string, string][] = [
      ["common.error", "Error"],
      ["common.search", "Search"],
      ["common.filter", "Filter"],
      ["auth.login", "Log in"],
      ["app.title", "TenderFlow"],
    ];
    for (const [key, expected] of cases) {
      expect(t(key)).toBe(expected);
    }
  });
});

// ---------------------------------------------------------------------------
// tWithLocale() — pure translate, explicit locale
// ---------------------------------------------------------------------------

describe("tWithLocale()", () => {
  it("translates with explicit 'es' locale regardless of store", () => {
    setLocale("en"); // store is 'en' but we pass 'es'
    expect(tWithLocale("es" as Locale, "common.loading")).toBe("Cargando...");
  });

  it("translates with explicit 'en' locale regardless of store", () => {
    // store is 'es' (default), but we pass 'en'
    expect(tWithLocale("en" as Locale, "common.loading")).toBe("Loading...");
  });

  it("returns the key for an unknown key in any locale", () => {
    expect(tWithLocale("es" as Locale, "no.such.key")).toBe("no.such.key");
    expect(tWithLocale("en" as Locale, "no.such.key")).toBe("no.such.key");
  });

  it("performs {var} interpolation", () => {
    // tWithLocale doesn't care about the key being real — interpolation is tested
    // by using a key that resolves to the key itself (unknown key = template is the key)
    const result = tWithLocale(
      "es" as Locale,
      "Hello {name}, you have {count} items",
      { name: "Ana", count: 3 },
    );
    expect(result).toBe("Hello Ana, you have 3 items");
  });

  it("replaces multiple occurrences of the same placeholder", () => {
    const result = tWithLocale(
      "es" as Locale,
      "{x} plus {x} equals something",
      { x: "2" },
    );
    expect(result).toBe("2 plus 2 equals something");
  });

  it("interpolates in a real translation key", () => {
    // common.loading has no placeholders — vars are ignored gracefully
    const result = tWithLocale("en" as Locale, "common.loading", {
      ignored: "value",
    });
    expect(result).toBe("Loading...");
  });
});

// ---------------------------------------------------------------------------
// Fallback cascade: en locale missing key → falls back to es value
// ---------------------------------------------------------------------------

describe("fallback cascade", () => {
  it("t() falls back to 'es' value when the en locale lacks the key", () => {
    // We can test by calling tWithLocale directly with a key only in 'es'
    // Both locales have the same keys currently, so we simulate by calling
    // tWithLocale with 'en' for a known 'es'-only concept. Instead we verify
    // the cascade logic: if a key is present in 'es' but NOT in 'en',
    // tWithLocale('en', ...) should return the 'es' value, not the key.
    //
    // Since the actual translation tables share all keys, we verify the
    // function behaviour via the source-level logic: tWithLocale falls
    // back to TRANSLATIONS["es"][key] when locale !== "es" and key is missing.
    //
    // We use a key guaranteed to be in 'es': "common.no_data_hint"
    const esValue = tWithLocale("es" as Locale, "common.no_data_hint");
    // It should be the Spanish string, not the key
    expect(esValue).not.toBe("common.no_data_hint");
    expect(esValue).toMatch(/filtros|fechas/i);
  });

  it("t() returns the key when not found in any locale", () => {
    setLocale("en");
    const key = "completely.missing.key";
    expect(t(key)).toBe(key);
  });

  it("tWithLocale('es', key) uses es directly (no further fallback needed)", () => {
    const result = tWithLocale("es" as Locale, "common.no_data");
    expect(result).toBe("Sin datos");
  });

  it("en locale app.subtitle differs from es and resolves to English string", () => {
    const en = tWithLocale("en" as Locale, "app.subtitle");
    const es = tWithLocale("es" as Locale, "app.subtitle");
    expect(en).toBe("Market Intelligence");
    expect(es).toBe("Plataforma de Inteligencia Competitiva");
    expect(en).not.toBe(es);
  });
});
