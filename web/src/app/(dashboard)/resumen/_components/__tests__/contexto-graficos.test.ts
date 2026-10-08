import { describe, expect, it } from "vitest";
import { puntosSparkline, tramosApilados } from "../contexto-graficos";

describe("puntosSparkline", () => {
  it("reparte la serie a lo ancho con el máximo arriba y el cero abajo", () => {
    expect(puntosSparkline([0, 10, 5], 100, 24)).toBe("0.00,23.00 50.00,1.00 100.00,12.00");
  });

  it("con menos de dos puntos no hay línea que dibujar", () => {
    expect(puntosSparkline([7], 100, 24)).toBe("");
    expect(puntosSparkline([], 100, 24)).toBe("");
  });

  it("una serie toda a cero se queda en el suelo, sin dividir por cero", () => {
    expect(puntosSparkline([0, 0], 100, 24)).toBe("0.00,23.00 100.00,23.00");
  });
});

describe("tramosApilados", () => {
  it("coloca cada estado donde acaba el anterior, en el orden en que llega", () => {
    const tramos = tramosApilados([
      { estado: "ADJ", n: 30, color: "a" },
      { estado: "PUB", n: 12, color: "b" },
      { estado: "EV", n: 3, color: "c" },
    ]);
    expect(tramos.map((t) => [t.estado, t.inicio])).toEqual([
      ["ADJ", 0],
      ["PUB", 30],
      ["EV", 42],
    ]);
  });
});
