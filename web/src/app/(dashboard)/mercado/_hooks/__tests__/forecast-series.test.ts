/**
 * `splitForecastSeries` es lo que corta la línea histórica justo donde arranca
 * la proyección, y `modeloLabel` lo que impide que la banda se lea como un
 * intervalo de confianza sin decir qué modelo la produjo. Las dos vivían
 * duplicadas en Tendencias y en Tendencias CPV, sin una sola prueba.
 *
 * El caso que fija el primer test es el que ya rompió una vez en producción: el
 * discriminante llega SIN tilde. Si el backend volviera a emitir "histórico",
 * ningún punto pasado casaría y la previsión se pintaría flotando.
 */
import { describe, expect, it } from "vitest";

import {
  modeloLabel,
  splitForecastSeries,
  type ForecastPoint,
} from "../forecast-series";

const SERIE: ForecastPoint[] = [
  { mes: "2026-07", valor: 100, tipo: "historico" },
  { mes: "2026-08", valor: 120, tipo: "historico" },
  { mes: "2026-09", valor: 130, tipo: "forecast", lower: 110, upper: 150 },
];

describe("splitForecastSeries", () => {
  it("reparte cada punto en su serie y deja la otra en undefined", () => {
    const filas = splitForecastSeries(SERIE);

    expect(filas).toEqual([
      { mes: "2026-07", historico: 100, forecast_val: undefined, lower: undefined, upper: undefined },
      { mes: "2026-08", historico: 120, forecast_val: undefined, lower: undefined, upper: undefined },
      { mes: "2026-09", historico: undefined, forecast_val: 130, lower: 110, upper: 150 },
    ]);
  });

  it("no arrastra la banda a los puntos históricos", () => {
    // Un histórico con lower/upper (el backend los ha emitido alguna vez)
    // ensancharía la banda hacia atrás, donde no hay incertidumbre que pintar.
    const filas = splitForecastSeries([
      { mes: "2026-07", valor: 100, tipo: "historico", lower: 90, upper: 110 },
    ]);

    expect(filas[0].lower).toBeUndefined();
    expect(filas[0].upper).toBeUndefined();
  });

  it("devuelve lista vacía si el endpoint aún no respondió", () => {
    expect(splitForecastSeries(undefined)).toEqual([]);
  });
});

describe("modeloLabel", () => {
  it("traduce los dos motores conocidos", () => {
    expect(modeloLabel("holt-winters")).toBe("Holt-Winters (suavizado exponencial)");
    expect(modeloLabel("regresion-lineal")).toBe("regresión lineal (fallback)");
  });

  it("devuelve el crudo si el backend añade otro motor", () => {
    expect(modeloLabel("arima")).toBe("arima");
  });

  it("no rotula nada cuando el backend no declara modelo", () => {
    expect(modeloLabel(null)).toBeNull();
    expect(modeloLabel(undefined)).toBeNull();
  });
});
