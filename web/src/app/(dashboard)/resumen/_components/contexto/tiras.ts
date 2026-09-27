/** Convenciones que comparten las dos tiras de `overview`. */

/**
 * Pie de los indicadores que el backend calcula sobre la tabla entera, sin
 * aplicar el ámbito.
 *
 * En una pantalla con chips de ámbito activos, un número global sin marcar es
 * un número que miente: dice «tu mercado» y mide todo el mercado. Va en el pie
 * de la celda, en palabras de quien la lee y corto: el pie se trunca a un
 * sexto del ancho, y lo último que se cortaría es justo la salvedad.
 */
export const GLOBAL = "sin tu ámbito";
