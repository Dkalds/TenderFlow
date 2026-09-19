import { describe, it, expect } from "vitest";
import { documentosNuevos } from "@/lib/documento-nuevo";

const AHORA = Date.parse("2026-09-19T12:00:00Z");

describe("documentosNuevos", () => {
  it("no marca el primer lote de un expediente recién publicado", () => {
    const nuevos = documentosNuevos(
      [
        { id: 1, created_at: "2026-09-18T10:00:00Z" },
        { id: 2, created_at: "2026-09-18T10:05:00Z" },
      ],
      AHORA,
    );
    expect(nuevos.size).toBe(0);
  });

  it("marca el documento que llegó después del primer lote, dentro de siete días", () => {
    const nuevos = documentosNuevos(
      [
        { id: 1, created_at: "2026-08-01T10:00:00Z" },
        { id: 2, created_at: "2026-09-15T10:00:00Z" },
      ],
      AHORA,
    );
    expect([...nuevos]).toEqual([2]);
  });

  it("deja de marcarlo pasados siete días", () => {
    const nuevos = documentosNuevos(
      [
        { id: 1, created_at: "2026-08-01T10:00:00Z" },
        { id: 2, created_at: "2026-09-10T10:00:00Z" },
      ],
      AHORA,
    );
    expect(nuevos.size).toBe(0);
  });

  it("ignora fechas ausentes o ilegibles", () => {
    expect(documentosNuevos([{ id: 1, created_at: null }, { id: 2, created_at: "x" }], AHORA).size).toBe(0);
  });
});
