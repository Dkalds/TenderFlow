import { describe, expect, it } from "vitest";
import { celdaSalud, celdaSaludPorPct, coberturaSinMedir, valorOEmpty } from "@/lib/cobertura";
import { EMPTY, formatCurrency, formatPercent } from "@/lib/utils";

/**
 * La regla que este módulo hace ejecutable: un porcentaje cuyo denominador no
 * se conoce no se publica.
 *
 * Vivía dentro de `resumen/_components/contexto-strip.tsx` y por eso solo
 * regía en esa pantalla: `/competidores`, un clic más allá, publicaba las
 * mismas magnitudes sin acotar y convertía los nulos en `0 %`.
 */

describe("celdaSalud", () => {
  it("publica el valor cuando la cobertura es suficiente", () => {
    const celda = celdaSalud(12.4, { cobertura_pct: 81, suficiente: true }, "sobre el ámbito");
    expect(celda.value).toBe(formatPercent(12.4));
    expect(celda.hint).toContain("sobre el ámbito");
  });

  it("se abstiene con cobertura insuficiente, y dice cuánta hay", () => {
    // No un número atenuado: un 93,1 % en gris sigue siendo un 93,1 % en la
    // cabeza de quien lo lee.
    const celda = celdaSalud(93.1, { cobertura_pct: 3.4, suficiente: false }, "glosa");
    expect(celda.value).toBe(EMPTY);
    expect(celda.hint).toContain("3,4");
  });

  it("se abstiene si la cobertura no está medida, sin fingir que es baja", () => {
    const celda = celdaSalud(50, undefined, "glosa");
    expect(celda.value).toBe(EMPTY);
    expect(celda.hint).toBe("sin cobertura medida del dato de origen");
  });

  it("un `suficiente` ausente no autoriza a publicar", () => {
    // Es lo que ve un cliente contra un backend anterior al campo: la salida
    // segura es abstenerse, no asumir que sí.
    expect(celdaSalud(50, { cobertura_pct: 90 }, "glosa").value).toBe(EMPTY);
  });

  // Los tres casos de abajo vivían en el test de la tira de salud del
  // Resumen, que se retiró de la pantalla (2026-10): fijan los textos exactos
  // del pie, que siguen siendo los de `/competidores`.
  it("dice exactamente cuánta cobertura hay cuando se abstiene", () => {
    const celda = celdaSalud(
      93.1,
      { base: 5780, universo: 170000, cobertura_pct: 3.4, umbral_pct: 50, suficiente: false },
      "adjudicaciones con 1 oferta",
    );
    expect(celda.value).toBe(EMPTY);
    expect(celda.hint).toBe("solo 3,4% de las adjudicaciones traen el dato");
  });

  it("no confunde «cobertura 0 %» con «cobertura sin medir»", () => {
    const celda = celdaSalud(93.1, { cobertura_pct: 0, suficiente: false }, "glosa");
    expect(celda.hint).toBe("solo 0,0% de las adjudicaciones traen el dato");
  });

  it("al publicar, deja la cobertura al pie junto a la glosa", () => {
    const glosa = "adjudicaciones con 1 oferta";
    const celda = celdaSalud(
      41.5,
      { base: 150000, universo: 170000, cobertura_pct: 88.2, umbral_pct: 50, suficiente: true },
      glosa,
    );
    expect(celda.value).toBe("41,5%");
    expect(celda.hint).toBe(`${glosa} · cobertura 88,2%`);
  });
});

describe("coberturaSinMedir", () => {
  it("distingue «no lo sé» de «es baja»", () => {
    expect(coberturaSinMedir(undefined)).toBe(true);
    expect(coberturaSinMedir({ cobertura_pct: null })).toBe(true);
    expect(coberturaSinMedir({ cobertura_pct: 0 })).toBe(false);
  });
});

describe("celdaSaludPorPct", () => {
  it("publica por encima del umbral", () => {
    expect(celdaSaludPorPct(12.4, 55, "glosa").value).toBe(formatPercent(12.4));
  });

  it("se abstiene por debajo del umbral", () => {
    expect(celdaSaludPorPct(12.4, 5, "glosa").value).toBe(EMPTY);
  });

  it("se abstiene sin denominador", () => {
    // `/analytics/competitors` manda `cobertura_ofertas_pct` a `null` cuando no
    // hay adjudicaciones en el ámbito, y un backend anterior al campo no lo
    // manda.
    expect(celdaSaludPorPct(12.4, null, "glosa").value).toBe(EMPTY);
    expect(celdaSaludPorPct(12.4, undefined, "glosa").value).toBe(EMPTY);
  });

  it("el umbral por defecto es el del backend, no uno más laxo", () => {
    // `UMBRAL_COBERTURA_PCT` en `services/analytics/overview.py`. Con un
    // umbral propio más bajo, esta pantalla publicaba lo que el backend no da
    // por hecho.
    expect(celdaSaludPorPct(12.4, 50, "glosa").value).toBe(formatPercent(12.4));
    const justoDebajo = celdaSaludPorPct(12.4, 49.9, "glosa");
    expect(justoDebajo.value).toBe(EMPTY);
    expect(justoDebajo.hint).toBe("solo 49,9% de las adjudicaciones traen el dato");
  });

  it("el umbral se puede subir en la llamada", () => {
    expect(celdaSaludPorPct(12.4, 55, "glosa").value).toBe(formatPercent(12.4));
    expect(celdaSaludPorPct(12.4, 55, "glosa", 60).value).toBe(EMPTY);
  });
});

describe("valorOEmpty", () => {
  it("formatea lo que existe", () => {
    expect(valorOEmpty(1200, formatCurrency)).toBe(formatCurrency(1200));
  });

  it("no convierte la ausencia en cero", () => {
    // `?? 0` afirmaba "0 €" de importe total y "0 %" de tasa de adjudicación.
    expect(valorOEmpty(null, formatCurrency)).toBe(EMPTY);
    expect(valorOEmpty(undefined, formatPercent)).toBe(EMPTY);
  });

  it("un cero real sí se publica", () => {
    // La distinción entera del módulo: 0 es un dato, `null` es su ausencia.
    expect(valorOEmpty(0, formatPercent)).toBe(formatPercent(0));
  });
});
