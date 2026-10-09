import { describe, it, expect } from "vitest";
import { SOURCE_LABELS, SOURCE_HINTS, sourceLabel, sourceHint } from "../_lib/source-label";

// Los valores que puede devolver POST /api/v1/search/semantic. La versión
// Python de esta comprobación (tests/test_search_semantic_source.py) es la que
// impide que este array y la búsqueda se separen; aquí se fija el
// comportamiento de la función ante lo que llega por la red.
const FUENTES = ["rrf", "fts", "like", "filtros"];

describe("sourceLabel", () => {
  it("etiqueta todas las fuentes de la búsqueda", () => {
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
    // Si la búsqueda gana un camino nuevo, la UI dice cuál es aunque no sepa
    // nombrarlo: el fallo caro es enseñar una etiqueta falsa.
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

  it("la búsqueda por texto no se explica como la falta de otra cosa", () => {
    // La pista anterior decía «Sin pliegos indexados que combinar» con 345.000
    // fragmentos indexados: lo que faltaba era otra cosa, y no era asunto de
    // quien busca.
    expect(SOURCE_HINTS.fts).not.toMatch(/^Sin /);
    expect(SOURCE_HINTS.fts).toMatch(/pliegos/);
  });
});
