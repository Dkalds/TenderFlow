import { describe, expect, it } from "vitest";
import { esValorLegalPlaceholder } from "../legal-placeholder";

/**
 * El guard que faltaba.
 *
 * `next.config.ts` comprobaba que las variables `NEXT_PUBLIC_LEGAL_*` no
 * estuvieran vacías, y una variable rellena con un recordatorio pasa esa
 * comprobación. En producción se leía, literalmente, «Responsable: PLACEHOLDER
 * LOCAL - NO DESPLEGAR, con NIF X0000000X». Los tres primeros casos de abajo son
 * esos valores exactos: si alguien relaja el predicado, vuelven a publicarse.
 */
describe("esValorLegalPlaceholder", () => {
  it.each([
    ["PLACEHOLDER LOCAL - NO DESPLEGAR", "la razón social que se publicó"],
    ["X0000000X", "el NIF de relleno"],
    ["Domicilio de desarrollo, sin validez legal", "el domicilio de relleno"],
  ])("%s es relleno (%s)", (valor) => {
    expect(esValorLegalPlaceholder(valor)).toBe(true);
  });

  it.each<[string | null | undefined, string]>([
    [undefined, "la variable sin definir"],
    [null, "el valor nulo"],
    ["", "la cadena vacía"],
    ["   ", "sólo espacios"],
  ])("%s cuenta como ausente (%s)", (valor) => {
    expect(esValorLegalPlaceholder(valor)).toBe(true);
  });

  it("caza la marca aunque venga con otra caja o con acentos", () => {
    // Un valor escrito a mano en el panel de Vercel no respeta ninguna
    // convención: normalizar es lo que hace que el guard no dependa de cómo lo
    // tecleó quien lo puso.
    expect(esValorLegalPlaceholder("Dirección De Desarrollo")).toBe(true);
    expect(esValorLegalPlaceholder("PENDIENTE de escritura")).toBe(true);
    expect(esValorLegalPlaceholder("Vía de Ejemplo, 3")).toBe(true);
  });

  it.each([
    ["Tenderflow Analytics, S.L.", "una razón social"],
    ["R9800000J", "un NIF real"],
    ["Paseo de la Castellana 100, 28046 Madrid", "un domicilio real"],
    ["S.L.", "una forma societaria suelta"],
  ])("%s es un dato válido (%s)", (valor) => {
    expect(esValorLegalPlaceholder(valor)).toBe(false);
  });

  it("recorta antes de decidir", () => {
    expect(esValorLegalPlaceholder("  Tenderflow Analytics, S.L.  ")).toBe(false);
  });
});
