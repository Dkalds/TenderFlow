/**
 * Mover un peso sin romper la suma.
 *
 * Los pesos son un reparto de 100: al subir uno, alguien tiene que bajar. Antes
 * lo hacía el usuario a mano, cuadrando seis deslizadores hasta el 100 exacto;
 * aquí el resto se reparte solo entre las demás dimensiones, en proporción a lo
 * que tenían. Las que el usuario ha **fijado** no se tocan.
 */

import { esPenalizacion } from "./pesos";

const TOTAL = 100;

/**
 * Reparte `total` entre `claves` en proporción a `base`, en enteros.
 *
 * Método del resto mayor: se da a cada una la parte entera y las unidades que
 * faltan van a los restos más altos. A igual resto gana la que va antes en
 * `claves`, para que dos arrastres iguales den siempre el mismo reparto. Si
 * ninguna tenía peso, se reparte a partes iguales.
 */
function repartoProporcional(
  claves: readonly string[],
  base: Record<string, number>,
  total: number,
): Record<string, number> {
  const suma = claves.reduce((acumulado, clave) => acumulado + (base[clave] ?? 0), 0);
  const cuotas = claves.map((clave) =>
    suma > 0 ? ((base[clave] ?? 0) * total) / suma : total / claves.length,
  );
  const enteros = cuotas.map(Math.floor);
  let faltan = total - enteros.reduce((a, b) => a + b, 0);
  const porResto = cuotas
    .map((cuota, indice) => ({ indice, resto: cuota - enteros[indice] }))
    .sort((a, b) => b.resto - a.resto || a.indice - b.indice);
  for (const { indice } of porResto) {
    if (faltan <= 0) break;
    enteros[indice] += 1;
    faltan -= 1;
  }
  return Object.fromEntries(claves.map((clave, indice) => [clave, enteros[indice]]));
}

/** Lo máximo que puede valer `clave` sin tocar las fijadas. */
export function topeDePeso(
  pesos: Record<string, number>,
  clave: string,
  fijadas: ReadonlySet<string>,
): number {
  const reservado = Object.entries(pesos)
    .filter(([otra]) => otra !== clave && !esPenalizacion(otra) && fijadas.has(otra))
    .reduce((acumulado, [, valor]) => acumulado + valor, 0);
  return Math.max(0, TOTAL - reservado);
}

/** Dimensiones que absorben el cambio de `clave`: ni ella, ni fijadas, ni penalizaciones. */
export function dimensionesLibres(
  pesos: Record<string, number>,
  clave: string,
  fijadas: ReadonlySet<string>,
): string[] {
  return Object.keys(pesos).filter(
    (otra) => otra !== clave && !esPenalizacion(otra) && !fijadas.has(otra),
  );
}

/**
 * Pone `clave` en `valor` y reparte lo que sobra o falta entre las libres.
 *
 * `base` son los pesos de **antes de empezar el gesto**, no los del paso
 * anterior: repartir sobre lo ya repartido pierde las proporciones en cuanto
 * un arrastre pasa por 100 (todas las demás a 0) y vuelve.
 *
 * Si no queda ninguna dimensión libre, `clave` no se puede mover: su valor es
 * el único que cuadra la suma, y se devuelve ese.
 */
export function repartirPesos(
  base: Record<string, number>,
  clave: string,
  valor: number,
  fijadas: ReadonlySet<string> = new Set(),
): Record<string, number> {
  const libres = dimensionesLibres(base, clave, fijadas);
  const tope = topeDePeso(base, clave, fijadas);
  const pedido = Math.min(Math.max(Math.round(valor), 0), tope);
  const asignado = libres.length === 0 ? tope : pedido;
  return {
    ...base,
    [clave]: asignado,
    ...repartoProporcional(libres, base, tope - asignado),
  };
}
