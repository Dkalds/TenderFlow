import { describe, expect, it } from "vitest";
import { tramosApilados } from "../contexto-graficos";

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
