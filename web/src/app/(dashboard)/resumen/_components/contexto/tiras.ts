/** Convenciones que comparten las dos tiras de `overview`. */

/**
 * Rejilla ancha: en `lg` las celdas se reparten según las columnas que la tira
 * declare, que no son las mismas en las dos (la de salud retira las celdas sin
 * cobertura medida).
 */
export const STRIP_LG = "lg:grid-cols-[repeat(var(--console-stat-columns),minmax(0,1fr))]";

/**
 * Pie de los indicadores que el backend calcula sobre la tabla entera.
 *
 * En una pantalla con chips de ámbito activos, un número global sin marcar es
 * un número que miente: dice «tu mercado» y mide el corpus.
 */
export const GLOBAL = "corpus completo, no el ámbito";
