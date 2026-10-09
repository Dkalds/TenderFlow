/**
 * Tests de `_hooks/casillas-ccaa.ts`: el mapa de casillas del perfil.
 *
 * Lo que importa es que ninguna comunidad se pierda en silencio: un nombre que
 * no encuentra casilla (una variante que el backend no normalizó) tiene que
 * seguir en pantalla, fuera de la rejilla, con su cifra.
 */
import { describe, it, expect } from "vitest";

import { buildCasillas, casillaDe } from "../_hooks/casillas-ccaa";

const fila = (label: string, cuota_empresa_pct: number, contratos = 1) => ({
  codigo: null,
  label,
  contratos,
  importe: 0,
  cuota_empresa_pct,
});

describe("casillaDe", () => {
  it("encuentra los nombres canónicos del backend", () => {
    expect(casillaDe("Madrid")?.codigo).toBe("MD");
    expect(casillaDe("Comunidad Valenciana")?.codigo).toBe("VC");
    expect(casillaDe("Castilla-La Mancha")?.codigo).toBe("CM");
    expect(casillaDe("Baleares")?.codigo).toBe("IB");
  });

  it("y las variantes con las que llegan de la fuente", () => {
    expect(casillaDe("Comunidad de Madrid")?.codigo).toBe("MD");
    expect(casillaDe("COMUNITAT VALENCIANA")?.codigo).toBe("VC");
    expect(casillaDe("Illes Balears")?.codigo).toBe("IB");
    expect(casillaDe("Castilla y Leon")?.codigo).toBe("CL");
    expect(casillaDe("Región de Murcia")?.codigo).toBe("MC");
  });

  it("un nombre desconocido no tiene casilla", () => {
    expect(casillaDe("Extranjero")).toBeNull();
    expect(casillaDe("")).toBeNull();
  });
});

describe("buildCasillas", () => {
  it("las diecinueve casillas, con dato o sin él", () => {
    const { casillas } = buildCasillas([fila("Madrid", 60)]);
    expect(casillas).toHaveLength(19);
    expect(casillas.filter((c) => c.pct != null).map((c) => c.codigo)).toEqual(["MD"]);
  });

  it("la intensidad va en cinco pasos, relativa a la comunidad de más peso", () => {
    const { casillas } = buildCasillas([fila("Madrid", 60), fila("Cataluña", 30), fila("Galicia", 3)]);
    const paso = (codigo: string) => casillas.find((c) => c.codigo === codigo)?.paso;
    expect(paso("MD")).toBe(5);
    expect(paso("CT")).toBe(3);
    expect(paso("GA")).toBe(1);
    // Sin adjudicaciones: casilla vacía, no el paso más claro.
    expect(paso("AN")).toBe(0);
  });

  it("conserva la cifra y el recuento de la API", () => {
    const madrid = buildCasillas([fila("Madrid", 41.5, 12)]).casillas.find((c) => c.codigo === "MD");
    expect(madrid).toMatchObject({ nombre: "Madrid", pct: 41.5, contratos: 12 });
  });

  it("una comunidad sin casilla no se pierde: va aparte, con su cifra", () => {
    const { casillas, sinCasilla } = buildCasillas([fila("Madrid", 70), fila("Extranjero", 30, 2)]);
    expect(sinCasilla).toEqual([{ nombre: "Extranjero", pct: 30, contratos: 2 }]);
    expect(casillas.filter((c) => c.pct != null)).toHaveLength(1);
  });

  it("sin datos, la rejilla entera queda vacía", () => {
    const { casillas, sinCasilla } = buildCasillas([]);
    expect(casillas.every((c) => c.paso === 0 && c.pct == null)).toBe(true);
    expect(sinCasilla).toEqual([]);
  });
});
