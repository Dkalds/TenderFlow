/*
 * Módulo propio y sin dependencias: lo importa el modelo de la tabla de
 * Detalle, que también corre en el prefetch de servidor (`detalle/_lib/prefetch.ts`).
 * Desde `lib/export.ts` arrastraba `lib/toast` y, con él, Sonner como referencia
 * de cliente en el First Load de /detalle.
 */

/**
 * Lo que un cliente de hojas de cálculo evalúa como fórmula: `=`, `+`, `-` o
 * `@` al empezar la celda, también tras los blancos que algunos motores recortan
 * antes de decidirlo (misma lista que `_LEADING_IGNORABLES` de
 * `shared/export_safety.py`, la del CSV de servidor), o una celda que arranca
 * por tabulador o retorno de carro.
 */
const PREFIJO_DE_FORMULA = /^(?:[ \t\r\n ​]*[=+\-@]|[\t\r])/;

/**
 * Deja un texto como literal en una hoja de cálculo: si Excel lo ejecutaría al
 * abrir el fichero (inyección CSV), un apóstrofo delante lo vuelve texto. Los
 * títulos y órganos son texto de terceros, así que esto no es teórico.
 */
export function neutralizarFormula(text: string): string {
  return PREFIJO_DE_FORMULA.test(text) ? `'${text}` : text;
}
