/**
 * Orden, selección, ventana de paginación y CSV: las funciones puras con las
 * que la tabla decide qué está marcado, qué página se pinta y qué se exporta.
 */
import { describe, it, expect } from "vitest";
import type { SortingState } from "@tanstack/react-table";
import {
  buildCsv,
  isClientSorted,
  nextSorting,
  pageIdsOf,
  pageWindowFor,
  toggleAllPageSelection,
  toggleRowSelection,
  totalPagesFor,
} from "../_hooks/detalle-table-model";
import { row } from "./detalle-fixtures";


describe("isClientSorted", () => {
  it("distingue orden de servidor de orden de página", () => {
    expect(isClientSorted([])).toBe(false);
    expect(isClientSorted([{ id: "importe", desc: false }])).toBe(false);
    expect(isClientSorted([{ id: "estado", desc: false }])).toBe(true);
  });
});

/* ── ciclo de orden y selección ─────────────────────────────────────── */

describe("nextSorting", () => {
  it("recorre asc → desc → sin orden en la misma columna", () => {
    let sorting: SortingState = [];
    sorting = nextSorting(sorting, "importe");
    expect(sorting).toEqual([{ id: "importe", desc: false }]);
    sorting = nextSorting(sorting, "importe");
    expect(sorting).toEqual([{ id: "importe", desc: true }]);
    sorting = nextSorting(sorting, "importe");
    expect(sorting).toEqual([]);
  });

  it("cambiar de columna reinicia en ascendente", () => {
    expect(nextSorting([{ id: "importe", desc: true }], "titulo")).toEqual([
      { id: "titulo", desc: false },
    ]);
  });
});

describe("selección", () => {
  it("alterna una fila quitándola del objeto al deseleccionar", () => {
    const once = toggleRowSelection({}, "A");
    expect(once).toEqual({ A: true });
    expect(toggleRowSelection(once, "A")).toEqual({});
  });

  it("no muta el estado recibido", () => {
    const current = { A: true };
    toggleRowSelection(current, "B");
    expect(current).toEqual({ A: true });
  });

  it("select-all marca toda la página sin tocar selecciones de otras páginas", () => {
    const rows = [row({ id_externo: "A" }), row({ id_externo: "B" })];
    const next = toggleAllPageSelection({ Z: true }, rows, false);
    expect(next).toEqual({ Z: true, A: true, B: true });
  });

  it("select-all sobre una página ya marcada la desmarca entera", () => {
    const rows = [row({ id_externo: "A" }), row({ id_externo: "B" })];
    const next = toggleAllPageSelection({ Z: true, A: true, B: true }, rows, true);
    expect(next).toEqual({ Z: true });
  });
});

/* ── paginación ─────────────────────────────────────────────────────── */

describe("pageIdsOf", () => {
  it("son los id_externo de las filas visibles — lo que se pide al scoring", () => {
    expect(pageIdsOf([row({ id_externo: "A" }), row({ id_externo: "B" })])).toEqual([
      "A",
      "B",
    ]);
  });

  it("lista vacía mientras la página no ha cargado", () => {
    expect(pageIdsOf(undefined)).toEqual([]);
  });

  it("descarta las filas sin id", () => {
    expect(pageIdsOf([row({ id_externo: "A" }), row({ id_externo: "" })])).toEqual(["A"]);
  });
});

describe("paginación", () => {
  it("una página como mínimo aunque no haya resultados", () => {
    expect(totalPagesFor(0, 25)).toBe(1);
    expect(totalPagesFor(26, 25)).toBe(2);
    expect(totalPagesFor(50, 25)).toBe(2);
  });

  it("la ventana se recorta contra los extremos", () => {
    expect(pageWindowFor(0, 10)).toEqual([0, 1, 2]);
    expect(pageWindowFor(5, 10)).toEqual([3, 4, 5, 6, 7]);
    expect(pageWindowFor(9, 10)).toEqual([7, 8, 9]);
    expect(pageWindowFor(0, 1)).toEqual([0]);
  });
});

/* ── CSV ────────────────────────────────────────────────────────────── */

describe("buildCsv", () => {
  it("emite la cabecera aunque no haya filas", () => {
    expect(buildCsv([])).toBe(
      "id_externo,titulo,organo_contratacion,importe,estado,fecha_publicacion,ccaa,cpv,tecnologia",
    );
  });

  it("entrecomilla los valores con coma y duplica las comillas internas", () => {
    const csv = buildCsv([
      row({ id_externo: "A", titulo: 'Obras, fase 2 con "acta"', importe: 1000 }),
    ]);
    const [, line] = csv.split("\n");
    expect(line).toContain('"Obras, fase 2 con ""acta"""');
  });

  it("escribe los nulos como celda vacía, no como «null»", () => {
    const [, line] = buildCsv([row({ id_externo: "A" })]).split("\n");
    expect(line).toBe("A,,,,,,,,");
  });

  it("exporta solo las nueve columnas del contrato, en orden", () => {
    const csv = buildCsv([
      row({ id_externo: "A", ccaa: "MD", cpv: "72000000" } as never),
    ]);
    expect(csv.split("\n")[0].split(",")).toHaveLength(9);
  });
});
