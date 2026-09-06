/**
 * Tests de `_hooks/competidores-tabla.ts`: qué encuentra la búsqueda, cómo se
 * ordena cada columna, cuántas empresas caben en el comparador y qué
 * identidades agrega el dossier.
 *
 * Son funciones puras justamente para poder comprobarlas sin montar la
 * pantalla: la tabla real trae doce columnas y siete gráficos `dynamic()` que
 * en jsdom no pintan nada útil.
 */
import { describe, it, expect } from "vitest";

import {
  drillDownExtraParams,
  drillDownIds,
  filterBySearch,
  sortCompetitors,
  toggleCompareSelection,
} from "../_hooks/competidores-tabla";

import { ACME, BETA, GAMMA, competitor } from "./competidores-fixtures";

/* ── Búsqueda ───────────────────────────────────────────────────────── */

describe("filterBySearch", () => {
  it("devuelve la lista intacta sin término de búsqueda", () => {
    const items = [ACME, BETA];
    expect(filterBySearch(items, "")).toBe(items);
  });

  it("busca por nombre sin distinguir mayúsculas", () => {
    expect(filterBySearch([ACME, BETA], "acme")).toEqual([ACME]);
  });

  it("encuentra el grupo por el NIF de cualquiera de sus identidades", () => {
    // Un competidor fusionado tiene varios CIF; buscar el de una filial tiene
    // que devolver el grupo, no cero resultados.
    const grupo = competitor({
      nombre: "Holding XY",
      nif: "X00000000",
      nifs: ["X00000000", "Y99999999"],
    });
    expect(filterBySearch([grupo, ACME], "Y99999999")).toEqual([grupo]);
  });

  it("encuentra por variante de nombre", () => {
    const grupo = competitor({
      nombre: "Holding XY",
      nombres_variantes: ["XY Servicios SL", "XY Tecnología"],
    });
    expect(filterBySearch([grupo], "xy tecnolog")).toEqual([grupo]);
  });

  it("devuelve vacío si nada casa", () => {
    expect(filterBySearch([ACME, BETA], "zzz")).toEqual([]);
  });
});

/* ── Orden ──────────────────────────────────────────────────────────── */

describe("sortCompetitors", () => {
  it("ordena texto por locale y respeta el sentido", () => {
    const asc = sortCompetitors([GAMMA, ACME, BETA], "nombre", "asc");
    expect(asc.map((c) => c.nombre)).toEqual([
      "Acme Sistemas",
      "Beta Consulting",
      "Gamma Redes",
    ]);
    const desc = sortCompetitors([GAMMA, ACME, BETA], "nombre", "desc");
    expect(desc.map((c) => c.nombre)).toEqual([
      "Gamma Redes",
      "Beta Consulting",
      "Acme Sistemas",
    ]);
  });

  it("ordena números como números", () => {
    const asc = sortCompetitors([ACME, BETA, GAMMA], "count", "asc");
    expect(asc.map((c) => c.count)).toEqual([4, 7, 10]);
  });

  it("trata como cero las métricas opcionales ausentes", () => {
    const asc = sortCompetitors([ACME, GAMMA], "contratos_por_anio", "asc");
    expect(asc[0].nombre).toBe("Gamma Redes");
  });

  it("no muta la lista de entrada", () => {
    const items = [GAMMA, ACME];
    sortCompetitors(items, "count", "asc");
    expect(items[0]).toBe(GAMMA);
  });
});

describe("toggleCompareSelection", () => {
  it("añade hasta dos", () => {
    expect(toggleCompareSelection([], "A")).toEqual(["A"]);
    expect(toggleCompareSelection(["A"], "B")).toEqual(["A", "B"]);
  });

  it("con dos ya elegidos, la más antigua cede el sitio", () => {
    expect(toggleCompareSelection(["A", "B"], "C")).toEqual(["B", "C"]);
  });

  it("volver a marcar la misma la quita", () => {
    expect(toggleCompareSelection(["A", "B"], "A")).toEqual(["B"]);
  });
});

/* ── Drill-down ─────────────────────────────────────────────────────── */

describe("drill-down de un competidor agrupado", () => {
  it("sin empresa seleccionada no hay ids", () => {
    expect(drillDownIds(null)).toEqual([]);
  });

  it("deduplica empresa_id contra empresa_ids", () => {
    const grupo = competitor({ nombre: "G", empresa_id: 7, empresa_ids: [7, 8, 9] });
    expect(drillDownIds(grupo)).toEqual([7, 8, 9]);
  });

  it("una identidad suelta no manda empresa_ids", () => {
    const suelta = competitor({ nombre: "S", empresa_id: 42 });
    expect(drillDownIds(suelta)).toEqual([42]);
    expect(drillDownExtraParams([42])).toEqual({});
  });

  it("un grupo sí manda empresa_ids como lista separada por comas", () => {
    expect(drillDownExtraParams([7, 8, 9])).toEqual({ empresa_ids: "7,8,9" });
  });

  it("sin identidades no manda nada", () => {
    expect(drillDownExtraParams([])).toEqual({});
  });
});
