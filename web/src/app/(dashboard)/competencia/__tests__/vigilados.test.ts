/**
 * Tests de `_hooks/vigilados.ts`: dónde cae cada movimiento en la ventana de
 * 30 días y qué empresas de la tabla son las que vigilas.
 *
 * Las señales y la actividad las calcula el backend; aquí solo se comprueba la
 * geometría del carril y el cruce por identidad, que es lo que el árbol de
 * render no deja ver.
 */
import { describe, it, expect } from "vitest";

import type { Schemas } from "@/lib/api-types";

import { carrilesDeVigiladas, esVigilada, idsVigiladas, posicionEnVentana } from "../_hooks/vigilados";

import { ACME, GAMMA, competitor } from "./competidores-fixtures";

type Movimientos = Schemas["MovimientosVigiladasResult"];

const MOVIMIENTOS: Movimientos = {
  desde: "2026-09-09",
  dias: 30,
  senales_truncadas: false,
  empresas: [
    { empresa_id: 7, nombre: "Ejemplo Digital", adjudicaciones: 3, importe: 1_200_000 },
    { empresa_id: 8, nombre: "Norte Sistemas", adjudicaciones: 0, importe: 0 },
  ],
  senales: [
    {
      tipo: "nueva_ccaa",
      empresa_id: 7,
      empresa: "Ejemplo Digital",
      titulo: "Ejemplo Digital entra en Galicia",
      detalle: "Primera adjudicación en Galicia.",
      licitacion_id: "LIC-1",
      fecha: "2026-09-24",
      importe: 400_000,
    },
    {
      tipo: "racha",
      empresa_id: 7,
      empresa: "Ejemplo Digital",
      titulo: "Ejemplo Digital encadena 3 adjudicaciones",
      detalle: "3 en 30 días.",
    },
  ],
};

describe("posicionEnVentana", () => {
  it("la mitad de la ventana cae en el 50 %", () => {
    expect(posicionEnVentana("2026-09-24", "2026-09-09", 30)).toBe(50);
  });

  it("el primer día es el 0 y el último el 100", () => {
    expect(posicionEnVentana("2026-09-09", "2026-09-09", 30)).toBe(0);
    expect(posicionEnVentana("2026-10-09", "2026-09-09", 30)).toBe(100);
  });

  it("una fecha fuera de la ventana se queda en el borde, no fuera del carril", () => {
    expect(posicionEnVentana("2026-08-01", "2026-09-09", 30)).toBe(0);
    expect(posicionEnVentana("2026-12-01", "2026-09-09", 30)).toBe(100);
  });

  it("acepta fecha con hora", () => {
    expect(posicionEnVentana("2026-09-24T10:30:00", "2026-09-09", 30)).toBe(50);
  });

  it("sin fecha no hay posición", () => {
    // Una racha no ocurre un día: se lista debajo, no se clava en el carril.
    expect(posicionEnVentana(null, "2026-09-09", 30)).toBeNull();
    expect(posicionEnVentana(undefined, "2026-09-09", 30)).toBeNull();
    expect(posicionEnVentana("no es una fecha", "2026-09-09", 30)).toBeNull();
  });
});

describe("carrilesDeVigiladas", () => {
  it("un carril por empresa, en el orden de la API", () => {
    const carriles = carrilesDeVigiladas(MOVIMIENTOS);
    expect(carriles.map((c) => c.nombre)).toEqual(["Ejemplo Digital", "Norte Sistemas"]);
  });

  it("solo clava en el carril las señales con fecha de esa empresa", () => {
    const [ejemplo, norte] = carrilesDeVigiladas(MOVIMIENTOS);
    expect(ejemplo.marcas).toEqual([
      { tipo: "nueva_ccaa", x: 50, titulo: "Ejemplo Digital entra en Galicia", fecha: "2026-09-24" },
    ]);
    // La que no se ha movido sigue teniendo carril: se vigila igual.
    expect(norte.marcas).toEqual([]);
  });

  it("conserva la actividad que manda la API", () => {
    expect(carrilesDeVigiladas(MOVIMIENTOS)[0]).toMatchObject({ empresa_id: 7, adjudicaciones: 3, importe: 1_200_000 });
  });

  it("sin respuesta no hay carriles", () => {
    expect(carrilesDeVigiladas(undefined)).toEqual([]);
  });
});

describe("idsVigiladas y esVigilada", () => {
  const ids = idsVigiladas(MOVIMIENTOS);

  it("los ids de las empresas vigiladas", () => {
    expect([...ids]).toEqual([7, 8]);
    expect(idsVigiladas(undefined).size).toBe(0);
  });

  it("cruza por la identidad principal o por cualquiera del grupo", () => {
    expect(esVigilada(competitor({ nombre: "A", empresa_id: 7 }), ids)).toBe(true);
    expect(esVigilada(competitor({ nombre: "G", empresa_id: 1, empresa_ids: [1, 8] }), ids)).toBe(true);
    expect(esVigilada(ACME, ids)).toBe(false);
  });

  it("una empresa sin identidad en el maestro no puede estar vigilada", () => {
    expect(esVigilada(GAMMA, ids)).toBe(false);
  });
});
