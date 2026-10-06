/**
 * Navegación de la ficha completa: la anterior y la siguiente de la abierta,
 * en el orden de la página de la tabla (J/K y las flechas de la barra).
 */
import { describe, expect, it } from "vitest";
import { pasosDeFicha } from "../_hooks/use-ficha-completa";

const FILAS = [{ id_externo: "A" }, { id_externo: "B" }, { id_externo: "C" }];

describe("pasosDeFicha", () => {
  it("da la posición y las dos vecinas de una fila intermedia", () => {
    expect(pasosDeFicha(FILAS, "B")).toEqual({
      posicion: { indice: 1, total: 3 },
      anterior: { indice: 0, id: "A" },
      siguiente: { indice: 2, id: "C" },
    });
  });

  it("en los extremos falta la vecina de fuera", () => {
    expect(pasosDeFicha(FILAS, "A").anterior).toBeNull();
    expect(pasosDeFicha(FILAS, "C").siguiente).toBeNull();
  });

  it("una ficha abierta por permalink que no está en la página no tiene vecinas", () => {
    expect(pasosDeFicha(FILAS, "Z")).toEqual({ posicion: null, anterior: null, siguiente: null });
    expect(pasosDeFicha(FILAS, null)).toEqual({ posicion: null, anterior: null, siguiente: null });
  });
});
