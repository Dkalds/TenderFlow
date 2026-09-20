import { describe, expect, it } from "vitest";
import { glosarioDeCodigo, normalizarCodigo, resolverCodigo } from "@/lib/procedimientos";

/** Forma de `GET /meta/filters` en lo que F1.7 consume: catálogos con definición. */
const META = {
  procedimiento: [
    { codigo: "1", etiqueta: "Abierto", descripcion: "Cualquier empresa puede presentar oferta." },
    { codigo: "9", etiqueta: "Abierto simplificado", descripcion: "Abierto con plazos cortos." },
  ],
  tramitacion: [{ codigo: "2", etiqueta: "Urgente", descripcion: "Plazos reducidos a la mitad." }],
  tipo_contrato: [],
};

describe("lib/procedimientos", () => {
  it("normaliza como el backend: sin espacios ni ceros a la izquierda", () => {
    expect(normalizarCodigo(" 01 ")).toBe("1");
    expect(normalizarCodigo("009")).toBe("9");
    expect(normalizarCodigo("A1")).toBe("A1");
    expect(normalizarCodigo("  ")).toBeNull();
    expect(normalizarCodigo(null)).toBeNull();
  });

  it("resuelve la etiqueta y la definición del catálogo, aunque llegue con cero", () => {
    expect(resolverCodigo(META, "procedimiento", "01")).toEqual({
      codigo: "1",
      etiqueta: "Abierto",
      descripcion: "Cualquier empresa puede presentar oferta.",
      catalogado: true,
    });
    expect(resolverCodigo(META, "tramitacion", "2")?.etiqueta).toBe("Urgente");
  });

  it("un código desconocido se muestra tal cual y como no catalogado", () => {
    expect(resolverCodigo(META, "procedimiento", "77")).toEqual({
      codigo: "77",
      etiqueta: "77",
      descripcion: null,
      catalogado: false,
    });
  });

  it("sin catálogo todavía no afirma que el código no esté catalogado", () => {
    expect(resolverCodigo(undefined, "procedimiento", "1")?.catalogado).toBe(true);
    expect(resolverCodigo(undefined, "procedimiento", "1")?.etiqueta).toBe("1");
  });

  it("sin código no hay nada que pintar", () => {
    expect(resolverCodigo(META, "procedimiento", null)).toBeNull();
    expect(resolverCodigo(META, "procedimiento", "")).toBeNull();
  });

  it("la ayuda de un código sin catalogar explica por qué se ve un número", () => {
    const resuelto = resolverCodigo(META, "procedimiento", "77")!;
    expect(glosarioDeCodigo("procedimiento", resuelto)?.definicion).toMatch(/todavía no está en el catálogo/);
    const abierto = resolverCodigo(META, "procedimiento", "1")!;
    expect(glosarioDeCodigo("procedimiento", abierto)).toEqual({
      termino: "Abierto",
      definicion: "Cualquier empresa puede presentar oferta.",
      ancla: "procedimientos",
    });
  });
});
