import { describe, it, expect } from "vitest";
import { tramosFinDeSemana } from "@/app/(dashboard)/resumen/_components/publicaciones/publicaciones-data";

// Octubre de 2026: el 10 y el 17 son sábado; el 11 y el 18, domingo.
describe("tramosFinDeSemana", () => {
  it("joins a Saturday and the Sunday after it into one band", () => {
    expect(tramosFinDeSemana(["2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19"])).toEqual([
      { desde: "2026-10-17", hasta: "2026-10-18" },
    ]);
  });

  it("keeps two weekends apart, and a weekend whose Sunday has no bar is just the Saturday", () => {
    expect(
      tramosFinDeSemana(["2026-10-09", "2026-10-10", "2026-10-12", "2026-10-17", "2026-10-18"]),
    ).toEqual([
      { desde: "2026-10-10", hasta: "2026-10-10" },
      { desde: "2026-10-17", hasta: "2026-10-18" },
    ]);
  });

  it("does not join a Sunday with the next Saturday", () => {
    expect(tramosFinDeSemana(["2026-10-11", "2026-10-17"])).toEqual([
      { desde: "2026-10-11", hasta: "2026-10-11" },
      { desde: "2026-10-17", hasta: "2026-10-17" },
    ]);
  });

  it("marks nothing on a series that is not daily", () => {
    expect(tramosFinDeSemana(["2026-W41", "2026-W42"])).toEqual([]);
    expect(tramosFinDeSemana([])).toEqual([]);
  });
});
