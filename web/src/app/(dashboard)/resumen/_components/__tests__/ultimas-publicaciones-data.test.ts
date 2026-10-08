import { describe, expect, it } from "vitest";
import {
  anchoImporte,
  fechaPublicacionCorta,
  ordenarPublicaciones,
} from "../ultimas-publicaciones-data";
import type { TimelineItem } from "../types";

function fila(id: string, extra: Partial<TimelineItem> = {}): TimelineItem {
  return {
    id_externo: id,
    titulo: `Expediente ${id}`,
    importe: 1000,
    fecha_publicacion: "2026-10-01T09:00:00+00:00",
    estado: "PUB",
    organo_contratacion: "Ministerio",
    tipo_contrato: "2",
    ccaa: "Madrid",
    fuente: "placsp",
    ...extra,
  };
}

describe("ordenarPublicaciones", () => {
  it("ordena el origen por el nombre del portal, no por su clave interna", () => {
    const items = [fila("A", { fuente: "ted" }), fila("B", { fuente: "euskadi_rss" }), fila("C", { fuente: "placsp" })];
    expect(ordenarPublicaciones(items, "fuente", "asc").map((f) => f.id_externo)).toEqual(["B", "C", "A"]);
  });

  it("deja al final las filas sin valor, en los dos sentidos", () => {
    const items = [fila("A", { importe: null }), fila("B", { importe: 5 }), fila("C", { importe: 9 })];
    expect(ordenarPublicaciones(items, "importe", "desc").map((f) => f.id_externo)).toEqual(["C", "B", "A"]);
    expect(ordenarPublicaciones(items, "importe", "asc").map((f) => f.id_externo)).toEqual(["B", "C", "A"]);
  });

  it("no muta la lista que recibe", () => {
    const items = [fila("B"), fila("A")];
    ordenarPublicaciones(items, "id_externo", "asc");
    expect(items.map((f) => f.id_externo)).toEqual(["B", "A"]);
  });
});

describe("anchoImporte", () => {
  it("reparte de 100 € a 10 M€ en escala logarítmica", () => {
    expect(anchoImporte(100)).toBe(2);
    expect(anchoImporte(10_000)).toBeCloseTo(40);
    expect(anchoImporte(10_000_000)).toBe(100);
    expect(anchoImporte(50_000_000)).toBe(100);
  });

  it("sin importe no hay barra", () => {
    expect(anchoImporte(null)).toBe(0);
    expect(anchoImporte(0)).toBe(0);
  });
});

describe("fechaPublicacionCorta", () => {
  const ahora = new Date(2026, 9, 8, 12, 13);

  it("lo de hoy y ayer lleva la hora", () => {
    expect(fechaPublicacionCorta(new Date(2026, 9, 8, 9, 5).toISOString(), ahora)).toBe("hoy 09:05");
    expect(fechaPublicacionCorta(new Date(2026, 9, 7, 17, 32).toISOString(), ahora)).toBe("ayer 17:32");
  });

  it("lo anterior, la fecha", () => {
    const fecha = new Date(2026, 9, 2, 10, 0).toISOString();
    expect(fechaPublicacionCorta(fecha, ahora)).not.toMatch(/^(hoy|ayer)/);
    expect(fechaPublicacionCorta(fecha, ahora)).toContain("2026");
  });

  it("sin fecha legible, la raya de vacío", () => {
    expect(fechaPublicacionCorta(null, ahora)).toBe("—");
    expect(fechaPublicacionCorta("no es fecha", ahora)).toBe("—");
  });
});
