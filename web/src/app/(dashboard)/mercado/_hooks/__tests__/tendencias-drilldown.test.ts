import { describe, expect, it } from "vitest";

/**
 * Tendencias (RFC ux-tendencias #1, #3) y Tendencias CPV (RFC #1).
 *
 * - El heatmap Mes×Estado gira las celdas REALES del backend; no hay producto
 *   de marginales que pueda colarse (ADR-014).
 * - El drill-down de mes/estado abre el listado con el mes completo.
 * - La previsión por CPV sólo pide códigos que la API acepta y cae a la global
 *   cuando el CPV elegido deja de estar pintado.
 */

import { heatmapFromCells, mesHref } from "../use-tendencias-view";
import { esCpvPrevisible, resolverForecastCpv } from "../use-tendencias-cpv-view";

describe("heatmapFromCells", () => {
  it("pinta los valores del cruce, no una distribución repartida", () => {
    const hm = heatmapFromCells([
      { row: "2026-02", col: "PUB", value: 10 },
      { row: "2026-01", col: "ADJ", value: 3 },
      { row: "2026-01", col: "PUB", value: 1 },
    ])!;
    expect(hm.meses).toEqual(["2026-01", "2026-02"]);
    // Por volumen total: PUB (11) antes que ADJ (3).
    expect(hm.estados).toEqual(["PUB", "ADJ"]);
    expect(hm.valores.get("2026-01|ADJ")).toBe(3);
    // Un mes sin ese estado es 0 de verdad, no la proporción global.
    expect(hm.valores.get("2026-02|ADJ")).toBeUndefined();
    expect(hm.maxVal).toBe(10);
  });

  it("sin celdas no hay heatmap", () => {
    expect(heatmapFromCells([])).toBeNull();
    expect(heatmapFromCells(undefined)).toBeNull();
  });
});

describe("mesHref", () => {
  it("cubre el mes entero, incluido febrero bisiesto", () => {
    expect(mesHref("2026-02")).toBe("/detalle?fecha_desde=2026-02-01&fecha_hasta=2026-02-28");
    expect(mesHref("2028-02")).toBe("/detalle?fecha_desde=2028-02-01&fecha_hasta=2028-02-29");
    expect(mesHref("2026-12")).toBe("/detalle?fecha_desde=2026-12-01&fecha_hasta=2026-12-31");
  });

  it("añade el estado de la celda", () => {
    expect(mesHref("2026-01", "ADJ")).toBe(
      "/detalle?fecha_desde=2026-01-01&fecha_hasta=2026-01-31&estado=ADJ",
    );
  });
});

describe("previsión por CPV", () => {
  it("sólo son previsibles los CPV de ocho dígitos", () => {
    expect(esCpvPrevisible("72267100")).toBe(true);
    expect(esCpvPrevisible("72267100-4")).toBe(true);
    expect(esCpvPrevisible("72")).toBe(false);
    expect(esCpvPrevisible("722671%")).toBe(false);
  });

  it("arranca en el primer CPV pintado, respeta la elección y el «mercado entero»", () => {
    const opciones = ["72267100", "48000000"];
    expect(resolverForecastCpv(undefined, opciones)).toBe("72267100");
    expect(resolverForecastCpv("48000000", opciones)).toBe("48000000");
    expect(resolverForecastCpv(null, opciones)).toBeNull();
  });

  it("si el CPV elegido deja de estar pintado, vuelve al primero (o a global)", () => {
    expect(resolverForecastCpv("99999999", ["72267100"])).toBe("72267100");
    expect(resolverForecastCpv("99999999", [])).toBeNull();
  });
});
