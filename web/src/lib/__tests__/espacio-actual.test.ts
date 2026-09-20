import { describe, expect, it } from "vitest";
import { espacioDeRuta } from "@/lib/espacio-actual";

describe("espacioDeRuta", () => {
  it("devuelve la clave del espacio de consola, no la ruta", () => {
    expect(espacioDeRuta("/radar")).toBe("radar");
    expect(espacioDeRuta("/oportunidades/42")).toBe("oportunidades");
  });

  it("una ruta que no es consola cae en `otro`", () => {
    expect(espacioDeRuta("/licitaciones/madrid/x/y")).toBe("otro");
    expect(espacioDeRuta(null)).toBe("otro");
  });
});
