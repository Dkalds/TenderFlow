import { describe, it, expect } from "vitest";
import { enumerar } from "@/app/(dashboard)/resumen/_components/alcance";

describe("enumerar", () => {
  it("no pone conjunción con un solo elemento", () => {
    expect(enumerar(["estado"])).toBe("estado");
  });

  it("une dos con «y»", () => {
    expect(enumerar(["búsqueda", "estado"])).toBe("búsqueda y estado");
  });

  it("usa comas y reserva la «y» para el último", () => {
    expect(enumerar(["búsqueda", "estado", "importe mínimo"])).toBe(
      "búsqueda, estado y importe mínimo",
    );
  });

  it("devuelve cadena vacía sin elementos", () => {
    expect(enumerar([])).toBe("");
  });
});
