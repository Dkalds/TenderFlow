/**
 * Las tres piezas puras que la consola del Investigador extrajo de la página:
 * el resaltado del extracto, los ajustes persistidos y el CSV.
 *
 * Se fijan aquí porque son las que no se ven en un E2E: el resaltado solo
 * aparece si la consulta cae dentro del extracto recortado, la configuración
 * guardada de una versión anterior tiene que seguir cargando, y el CSV lo lee
 * una hoja de cálculo, no una persona.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { highlightQuery } from "../_lib/highlight";
import { DEFAULT_CONFIG, loadConfig, saveConfig } from "../_lib/config-storage";
import { exportCSV } from "../_lib/export-csv";
import type { SearchResult } from "../_lib/types";

// Se tipa con la firma real de `@/lib/export` para que `mock.calls` llegue
// tipado y el Blob no haya que reafirmarlo con un `as`.
const descargarBlob = vi.hoisted(() =>
  vi.fn<(nombre: string, blob: Blob, recurso: "investigador") => void>(),
);
vi.mock("@/lib/export", () => ({ descargarBlob }));

describe("highlightQuery", () => {
  it("resalta la consulta dentro del extracto, sin distinguir mayúsculas", () => {
    render(<p>{highlightQuery("Mantenimiento SAP en Madrid", "sap")}</p>);
    const marca = screen.getByText("SAP");
    expect(marca.tagName).toBe("MARK");
  });

  it("no rompe con una consulta que contiene metacaracteres de RegExp", () => {
    // El usuario escribe lo que quiere: un `(` suelto tumbaba el render.
    expect(() => render(<p>{highlightQuery("Lote (1) de obra", "(1)")}</p>)).not.toThrow();
  });

  it("devuelve el texto tal cual cuando no hay consulta", () => {
    expect(highlightQuery("Sin consulta", "   ")).toBe("Sin consulta");
  });
});

describe("loadConfig", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("sin nada guardado devuelve los valores por defecto", () => {
    expect(loadConfig()).toEqual(DEFAULT_CONFIG);
  });

  it("completa con los valores por defecto las claves que el guardado no trae", () => {
    // Una configuración escrita antes de que existiera `alpha` no lo tiene; sin
    // el relleno, el deslizador de peso semántico arrancaría en `undefined`.
    window.localStorage.setItem("lsap:v1:investigador_config", JSON.stringify({ topK: 25 }));
    expect(loadConfig()).toEqual({ ...DEFAULT_CONFIG, topK: 25 });
  });

  it("lo guardado se vuelve a leer", () => {
    saveConfig({ ...DEFAULT_CONFIG, alpha: 0.25, model: "gpt-x" });
    expect(loadConfig().alpha).toBe(0.25);
    expect(loadConfig().model).toBe("gpt-x");
  });
});

describe("exportCSV", () => {
  beforeEach(() => {
    descargarBlob.mockClear();
  });

  async function csvEmitido(results: SearchResult[], source: string | null): Promise<string> {
    exportCSV(results, source);
    expect(descargarBlob).toHaveBeenCalledTimes(1);
    const [, blob] = descargarBlob.mock.calls[0];
    return await blob.text();
  }

  it("escribe la fuente de la respuesta en cada fila, no un campo por hit", async () => {
    // La columna se rellenaba con un campo que la API nunca ha devuelto por
    // hit, así que salía siempre vacía.
    const csv = await csvEmitido([{ id_externo: "A-1", titulo: "Obra" }], "rrf");
    const [cabecera, fila] = csv.split("\n");
    expect(cabecera.split(",").at(-1)).toBe("source");
    expect(fila.split(",").at(-1)).toBe("rrf");
  });

  it("escapa las comillas del título en vez de romper la columna", async () => {
    const csv = await csvEmitido([{ id_externo: "A-2", titulo: 'Obra "grande"' }], null);
    expect(csv.split("\n")[1]).toContain('"Obra ""grande"""');
  });

  it("se emite por `descargarBlob`, que es lo que mide la descarga", async () => {
    await csvEmitido([{ id_externo: "A-3" }], "fts");
    expect(descargarBlob.mock.calls[0][2]).toBe("investigador");
  });
});
