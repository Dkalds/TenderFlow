/**
 * Orden, selección, ventana de paginación y CSV: las funciones puras con las
 * que la tabla decide qué está marcado, qué página se pinta y qué se exporta.
 */
import { describe, it, expect, vi } from "vitest";
import type { RowSelectionState, SortingState } from "@tanstack/react-table";
import { descargarBlob } from "@/lib/export";
import { descargarSeleccion } from "../_components/detalle-seleccion";
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

vi.mock("@/lib/export", () => ({ descargarBlob: vi.fn() }));


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
    const current: RowSelectionState = { A: true };
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

  it("con cursor, la ventana no ofrece páginas sin cursor conocido", () => {
    // Vistas la 0 y la 1, y conocido el cursor de la 2: hasta ahí se puede ir.
    expect(pageWindowFor(1, 10, 3)).toEqual([0, 1, 2]);
    expect(pageWindowFor(0, 10, 1)).toEqual([0]);
  });
});

/* ── CSV ────────────────────────────────────────────────────────────── */

describe("buildCsv", () => {
  it("emite la cabecera aunque no haya filas", () => {
    expect(buildCsv([])).toBe(
      "id_externo;titulo;organo_contratacion;importe;estado;fecha_publicacion;ccaa;cpv;tecnologia",
    );
  });

  it("separa con punto y coma, como el CSV de la API: Excel en español lo abre en columnas", () => {
    // Con coma, Excel con configuración regional española metía la fila entera
    // en la columna A; `services/exports.py::generate_csv` ya usaba `;`.
    const csv = buildCsv([row({ id_externo: "A", titulo: "Obras, fase 2; lote 1", importe: 1000 })]);
    expect(csv.split("\n")[1]).toBe('A;"Obras, fase 2; lote 1";;1000;;;;;');
  });

  it("entrecomilla y duplica las comillas internas", () => {
    const csv = buildCsv([
      row({ id_externo: "A", titulo: 'Obras con "acta"', importe: 1000 }),
    ]);
    const [, line] = csv.split("\n");
    expect(line).toContain('"Obras con ""acta"""');
  });

  it("escribe los nulos como celda vacía, no como «null»", () => {
    const [, line] = buildCsv([row({ id_externo: "A" })]).split("\n");
    expect(line).toBe("A;;;;;;;;");
  });

  it("neutraliza como fórmula el texto de terceros que Excel ejecutaría al abrirlo", () => {
    const csv = buildCsv([
      row({ id_externo: "A", titulo: '=HYPERLINK("https://evil.example","ver")' }),
      row({ id_externo: "B", titulo: "@SUM(1+1)" }),
      row({ id_externo: "C", titulo: "-2+3" }),
      row({ id_externo: "D", titulo: "  =cmd|' /C calc'!A0" }),
    ]);
    const [, a, b, c, d] = csv.split("\n");
    expect(a).toBe(`A;"'=HYPERLINK(""https://evil.example"",""ver"")";;;;;;;`);
    expect(b).toBe("B;'@SUM(1+1);;;;;;;");
    expect(c).toBe("C;'-2+3;;;;;;;");
    // Los blancos de delante no la salvan: algunos motores los recortan antes
    // de decidir si es una fórmula.
    expect(d).toBe("D;'  =cmd|' /C calc'!A0;;;;;;;");
  });

  it("no toca un importe negativo: es un número, no una fórmula", () => {
    const [, line] = buildCsv([row({ id_externo: "A", importe: -50 })]).split("\n");
    expect(line).toBe("A;;;-50;;;;;");
  });

  it("entrecomilla los saltos de línea para que no partan la fila", () => {
    expect(buildCsv([row({ id_externo: "A", titulo: "uno\ndos" })])).toContain('A;"uno\ndos"');
  });

  it("exporta solo las nueve columnas del contrato, en orden", () => {
    const csv = buildCsv([
      row({ id_externo: "A", ccaa: "MD", cpv: "72000000" } as never),
    ]);
    expect(csv.split("\n")[0].split(";")).toHaveLength(9);
  });
});

describe("descargarSeleccion", () => {
  it("entrega el CSV con el BOM de UTF-8, sin el cual Excel rompe las tildes", async () => {
    descargarSeleccion([row({ id_externo: "A", titulo: "Gestión" })]);
    const blob = vi.mocked(descargarBlob).mock.calls[0][1];
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
  });
});
