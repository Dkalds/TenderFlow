import { describe, expect, it } from "vitest";
import { agruparPorDia } from "@/lib/agrupar-por-dia";

const ahora = new Date(2026, 9, 8, 12, 0);
const en = (dia: number, hora = 10) => new Date(2026, 9, dia, hora, 0).toISOString();

describe("agruparPorDia", () => {
  it("agrupa por día con «Hoy» y «Ayer», y conserva el orden en que llegan", () => {
    const grupos = agruparPorDia(
      [
        { id: "a", fecha: en(8, 11) },
        { id: "b", fecha: en(8, 9) },
        { id: "c", fecha: en(7) },
        { id: "d", fecha: en(5) },
      ],
      ahora,
    );
    expect(grupos.map((g) => [g.etiqueta.startsWith("5") ? "5 oct" : g.etiqueta, g.eventos.map((e) => e.id)])).toEqual([
      ["Hoy", ["a", "b"]],
      ["Ayer", ["c"]],
      ["5 oct", ["d"]],
    ]);
  });

  it("lo que no trae fecha legible va al final, en su propio grupo", () => {
    const grupos = agruparPorDia([{ id: "x", fecha: null }, { id: "y", fecha: en(8) }, { id: "z", fecha: "nunca" }], ahora);
    expect(grupos.map((g) => [g.etiqueta, g.eventos.map((e) => e.id)])).toEqual([
      ["Hoy", ["y"]],
      ["Sin fecha", ["x", "z"]],
    ]);
  });
});
