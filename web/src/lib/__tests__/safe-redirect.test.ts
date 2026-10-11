import { describe, expect, it } from "vitest";
import { safeRedirectPath } from "../safe-redirect";

describe("safeRedirectPath", () => {
  it("preserves an internal route", () => {
    expect(safeRedirectPath("/licitaciones?estado=abierta#results")).toBe(
      "/licitaciones?estado=abierta#results",
    );
  });

  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", null])(
    "rejects an external or malformed redirect: %s",
    (value) => {
      expect(safeRedirectPath(value)).toBe("/resumen");
    },
  );
});

/**
 * Los cuatro bloques de abajo salen del informe de mutación (Stryker,
 * 2026-10-11): cada uno es un filtro de `safeRedirectPath` que se podía quitar
 * o debilitar sin que fallara ningún test. No estaban rotos; nadie los vigilaba.
 */
describe("safeRedirectPath · cada filtro, por separado", () => {
  it("el límite de longitud está en 2.048 caracteres, incluido", () => {
    const justa = `/${"a".repeat(2_047)}`;
    const larga = `/${"a".repeat(2_048)}`;

    expect(justa).toHaveLength(2_048);
    expect(safeRedirectPath(justa)).toBe(justa);
    expect(safeRedirectPath(larga)).toBe("/resumen");
  });

  it("una ruta relativa, sin la barra inicial, no vale", () => {
    // Sin el filtro se resolvería contra el origen y saldría `/detalle?lic=1`:
    // interna, pero no lo que nadie escribió. El destino se acepta entero o no
    // se acepta.
    expect(safeRedirectPath("detalle?lic=1")).toBe("/resumen");
  });

  it("la doble barra se rechaza aunque apunte al host de referencia", () => {
    // El filtro de `//` no es redundante con la comprobación de origen:
    // `tenderflow.invalid` es el origen ficticio contra el que se resuelve, así
    // que esta URL la pasaría, y en el navegador `//host/…` es siempre otro sitio.
    expect(safeRedirectPath("//tenderflow.invalid/detalle")).toBe("/resumen");
  });

  it.each([
    ["tabulador", "/\t/evil.example"],
    ["salto de línea", "/\n/evil.example"],
    ["retorno de carro", "/\r/evil.example/entrar"],
  ])("un %s entre las dos barras no cuela otro host", (_caso, candidata) => {
    // El parser de URLs descarta esos tres caracteres, así que el texto no
    // empieza por `//` y la URL resultante sí: aquí es la comprobación de
    // origen la que lo para. `?redirect=/%09/evil.example` llega así.
    expect(safeRedirectPath(candidata)).toBe("/resumen");
  });
});
