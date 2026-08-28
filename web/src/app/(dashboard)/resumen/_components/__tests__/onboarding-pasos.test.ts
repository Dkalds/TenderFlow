import { describe, it, expect } from "vitest";
import {
  debeMostrarse,
  derivarPasos,
  estadoDe,
  etiquetaProgreso,
  progresoDe,
  PASOS,
} from "@/components/onboarding/pasos";
import { hayReglaActiva, perfilConfigurado, tienePursuits } from "@/components/onboarding/senales";
import type { Schemas, WatchlistRuleOut } from "@/lib/api-types";

/**
 * La regla que estos tests protegen es una sola, y es la que hace que la banda
 * sea honesta: **cargando no es «te falta»**. Colapsar los tres estados de una
 * query en un booleano haría que la pantalla de entrada abriese, durante unos
 * cientos de milisegundos, acusando de no tener configurado algo que sí está.
 */

describe("estadoDe", () => {
  it("distingue los cuatro casos sin colapsar cargando en pendiente", () => {
    expect(estadoDe(true)).toBe("hecho");
    expect(estadoDe(false)).toBe("pendiente");
    expect(estadoDe("cargando")).toBe("cargando");
    expect(estadoDe("error")).toBe("desconocido");
    expect(estadoDe(undefined)).toBe("desconocido");
  });
});

describe("debeMostrarse", () => {
  it("con todo hecho, la banda no existe", () => {
    const pasos = derivarPasos({ perfil: true, reglas: true, pursuit: true });
    expect(debeMostrarse(pasos)).toBe(false);
  });

  it("mientras se comprueba tampoco aparece", () => {
    const pasos = derivarPasos({ perfil: "cargando", reglas: "cargando", pursuit: "cargando" });
    expect(debeMostrarse(pasos)).toBe(false);
  });

  it("una API rota no inventa una banda de bienvenida", () => {
    const pasos = derivarPasos({ perfil: "error", reglas: "error", pursuit: "error" });
    expect(debeMostrarse(pasos)).toBe(false);
  });

  it("basta un pendiente acreditado para que valga la pena", () => {
    const pasos = derivarPasos({ perfil: true, reglas: false, pursuit: "cargando" });
    expect(debeMostrarse(pasos)).toBe(true);
  });
});

describe("progresoDe / etiquetaProgreso", () => {
  it("no cuenta como hecho lo que no ha resuelto", () => {
    const progreso = progresoDe(derivarPasos({ perfil: true, reglas: false, pursuit: "cargando" }));
    expect(progreso).toEqual({ hechos: 1, total: PASOS.length, sinResolver: 1 });
  });

  it("declara lo que falta por comprobar en vez de dar un total limpio", () => {
    expect(etiquetaProgreso({ hechos: 1, total: 3, sinResolver: 1 })).toBe(
      "1 de 3 hechos · 1 sin comprobar",
    );
    expect(etiquetaProgreso({ hechos: 2, total: 3, sinResolver: 0 })).toBe("2 de 3 hechos");
  });
});

describe("perfilConfigurado", () => {
  const vacio: Schemas["UserProfileOut"] = { visibility: "private" };

  it("el objeto vacío que devuelve la API sin perfil es «no configurado»", () => {
    expect(perfilConfigurado(vacio)).toBe(false);
  });

  it("acepta cualquier señal de que el usuario tocó el perfil", () => {
    expect(perfilConfigurado({ ...vacio, updated_at: "2026-08-01T00:00:00Z" })).toBe(true);
    expect(perfilConfigurado({ ...vacio, afinidad_keywords: ["SAP"] })).toBe(true);
    expect(perfilConfigurado({ ...vacio, cpvs: ["72000000"] })).toBe(true);
    expect(perfilConfigurado({ ...vacio, importe_min: 100_000 })).toBe(true);
    expect(perfilConfigurado({ ...vacio, weights: { importe: 100 } })).toBe(true);
  });

  it("no confunde listas vacías con contenido", () => {
    expect(perfilConfigurado({ ...vacio, afinidad_keywords: [], cpvs: [], weights: {} })).toBe(
      false,
    );
  });
});

describe("hayReglaActiva", () => {
  const regla = (active: boolean): WatchlistRuleOut => ({
    id: 1,
    active,
    email: null,
    frequency: "daily",
    match_count: 0,
    visibility: "private",
  });

  it("sin reglas, paso pendiente", () => {
    expect(hayReglaActiva([])).toBe(false);
  });

  it("una regla desactivada no vigila nada, así que no cuenta", () => {
    expect(hayReglaActiva([regla(false)])).toBe(false);
  });

  it("basta una activa", () => {
    expect(hayReglaActiva([regla(false), regla(true)])).toBe(true);
  });
});

describe("tienePursuits", () => {
  it("usa el total del backend, no la longitud de la página devuelta", () => {
    expect(tienePursuits({ total: 0 })).toBe(false);
    expect(tienePursuits({ total: 1 })).toBe(true);
  });
});
