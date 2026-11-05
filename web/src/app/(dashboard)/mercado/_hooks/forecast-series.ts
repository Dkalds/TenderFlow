/**
 * La serie de `/api/v1/analytics/forecast/volume`, y el único sitio donde se
 * parte en las cuatro claves que consumen los gráficos.
 *
 * Las dos vistas de series temporales de Mercado —Tendencias y Tendencias CPV—
 * pintan la misma previsión con el mismo `AreaChart`: banda `upper`/`lower`,
 * línea continua para el pasado y discontinua para la proyección. Cada una
 * tenía su copia del reparto, así que un cambio en el contrato del backend
 * había que acertarlo dos veces.
 *
 * No es un hook: es una función pura sobre el DTO, y por eso se puede probar
 * sin montar nada (`__tests__/forecast-series.test.ts`).
 */

import type { Schemas } from "@/lib/api-types";

/**
 * Un punto de la serie. `tipo` es "historico" o "forecast", SIN tilde: el
 * backend emitía "histórico" y las vistas comparaban contra "historico":
 * ningún punto pasado casaba, todos salían `undefined` y la proyección se
 * pintaba flotando, sin serie histórica contra la que contrastarla. El valor
 * normalizado lo fija `forecast.py`.
 */
export type ForecastPoint = Schemas["ForecastSeriesPoint"];

/**
 * `modelo`: motor que produjo la proyección ("holt-winters" |
 * "regresion-lineal"). `banda_sigmas`: sigmas de la banda `lower`/`upper`, no
 * un intervalo de confianza. `cpv`: CPV de la previsión; `null` = mercado.
 */
export type ForecastResponse = Schemas["ForecastVolumeResult"];

/** Fila del `AreaChart`: una clave por serie dibujada, `undefined` donde no aplica. */
export interface ForecastRow {
  mes: string;
  historico?: number;
  forecast_val?: number;
  lower?: number;
  upper?: number;
}

/**
 * Reparte cada punto en la serie que le toca. Un punto histórico deja
 * `forecast_val` y la banda en `undefined` (y viceversa), que es lo que corta
 * la línea continua justo donde arranca la discontinua.
 */
export function splitForecastSeries(series: ForecastPoint[] | undefined): ForecastRow[] {
  if (!series) return [];
  return series.map((p) => ({
    mes: p.mes,
    historico: p.tipo === "historico" ? p.valor : undefined,
    forecast_val: p.tipo === "forecast" ? p.valor : undefined,
    lower: p.tipo === "forecast" ? (p.lower ?? undefined) : undefined,
    upper: p.tipo === "forecast" ? (p.upper ?? undefined) : undefined,
  }));
}

/** Etiqueta legible del motor de forecast; el crudo si el backend añade otro. */
export function modeloLabel(modelo: string | null | undefined): string | null {
  if (!modelo) return null;
  if (modelo === "holt-winters") return "Holt-Winters (suavizado exponencial)";
  if (modelo === "regresion-lineal") return "regresión lineal (de respaldo)";
  return modelo;
}
