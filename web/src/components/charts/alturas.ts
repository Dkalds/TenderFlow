/**
 * Alturas de los gráficos que la pantalla necesita antes de cargarlos.
 *
 * El esqueleto y el vacío de un gráfico diferido (`next/dynamic`) reservan su
 * misma altura. Viven aquí, sin recharts, porque importar una constante del
 * módulo del gráfico mete el módulo entero —y recharts con él— en el First
 * Load de la pantalla.
 */

export const ALTO_MAPA_COMPETIDORES = 380;

export const ALTO_MAPA = 380;
