import { describe, it, expect } from "vitest";
import { SOURCE_LABELS, SOURCE_HINTS, sourceLabel, sourceHint } from "../_lib/source-label";

// Los tres valores que puede devolver POST /api/v1/search/semantic. La versión
// Python de esta comprobación (tests/test_search_semantic_source.py) es la que
// impide que este array y el backend se separen; aquí se fija el
// comportamiento de la función ante lo que llega por la red.
const FUENTES = ["rrf", "fts", "like"];

describe("sourceLabel", () => {
  it("etiqueta las tres fuentes del backend", () => {
    expect(Object.keys(SOURCE_LABELS).sort()).toEqual([...FUENTES].sort());
    for (const fuente of FUENTES) {
      expect(sourceLabel(fuente)).toBe(SOURCE_LABELS[fuente]);
    }
  });

  it("no etiqueta nada cuando aún no hubo búsqueda", () => {
    expect(sourceLabel(null)).toBeNull();
    expect(sourceLabel(undefined)).toBeNull();
    expect(sourceLabel("")).toBeNull();
  });

  it("devuelve tal cual una fuente que no conoce, en vez de ocultarla", () => {
    // Si el backend gana un camino nuevo, la UI dice cuál es aunque no sepa
    // nombrarlo: el fallo caro es pintar una etiqueta falsa.
    expect(sourceLabel("otro_motor")).toBe("otro_motor");
  });

  it("ninguna etiqueta cita un motor retirado", () => {
    const todas = Object.values(SOURCE_LABELS).join(" ");
    expect(todas).not.toMatch(/FAISS|FTS5/);
  });
});

describe("sourceHint", () => {
  it("explica cada fuente", () => {
    expect(Object.keys(SOURCE_HINTS).sort()).toEqual([...FUENTES].sort());
    for (const fuente of FUENTES) {
      expect(sourceHint(fuente)).toBe(SOURCE_HINTS[fuente]);
    }
  });

  it("no inventa explicación para una fuente desconocida", () => {
    expect(sourceHint("otro_motor")).toBeNull();
    expect(sourceHint(null)).toBeNull();
  });
});
