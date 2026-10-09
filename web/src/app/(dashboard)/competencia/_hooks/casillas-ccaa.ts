/**
 * El mapa de casillas del perfil: una casilla por comunidad autónoma, colocada
 * más o menos donde cae en el mapa, con la intensidad del peso que tiene en lo
 * que gana la empresa.
 *
 * No necesita geometría ni una librería de mapas: son diecinueve casillas en
 * una rejilla de 7 × 5. El coropleto de verdad vive en Mercado › Geografía.
 *
 * El peso de cada comunidad lo calcula el backend (`por_ccaa` del perfil). Aquí
 * solo se decide en qué casilla cae cada nombre y en cuál de cinco pasos de
 * intensidad se pinta.
 */

import { foldText } from "@/lib/utils";

interface CasillaBase {
  codigo: string;
  /** Nombre canónico del backend (`shared/geo.py`). */
  nombre: string;
  /** Posición en la rejilla, desde 1. */
  fila: number;
  columna: number;
}

const REJILLA: (CasillaBase & { alias: string[] })[] = [
  { codigo: "GA", nombre: "Galicia", fila: 1, columna: 1, alias: [] },
  { codigo: "AS", nombre: "Asturias", fila: 1, columna: 2, alias: ["principado de asturias"] },
  { codigo: "CB", nombre: "Cantabria", fila: 1, columna: 3, alias: [] },
  { codigo: "PV", nombre: "País Vasco", fila: 1, columna: 4, alias: ["euskadi"] },
  { codigo: "NA", nombre: "Navarra", fila: 1, columna: 5, alias: ["comunidad foral de navarra"] },
  { codigo: "CL", nombre: "Castilla y León", fila: 2, columna: 2, alias: [] },
  { codigo: "RI", nombre: "La Rioja", fila: 2, columna: 3, alias: ["rioja"] },
  { codigo: "AR", nombre: "Aragón", fila: 2, columna: 4, alias: [] },
  { codigo: "CT", nombre: "Cataluña", fila: 2, columna: 5, alias: ["catalunya"] },
  { codigo: "EX", nombre: "Extremadura", fila: 3, columna: 2, alias: [] },
  { codigo: "MD", nombre: "Madrid", fila: 3, columna: 3, alias: ["comunidad de madrid"] },
  { codigo: "CM", nombre: "Castilla-La Mancha", fila: 3, columna: 4, alias: ["castilla la mancha"] },
  {
    codigo: "VC",
    nombre: "Comunidad Valenciana",
    fila: 3,
    columna: 5,
    alias: ["comunitat valenciana", "valencia", "c. valenciana"],
  },
  { codigo: "IB", nombre: "Baleares", fila: 3, columna: 7, alias: ["islas baleares", "illes balears"] },
  { codigo: "AN", nombre: "Andalucía", fila: 4, columna: 3, alias: [] },
  { codigo: "MC", nombre: "Murcia", fila: 4, columna: 4, alias: ["region de murcia"] },
  { codigo: "CN", nombre: "Canarias", fila: 5, columna: 1, alias: ["islas canarias"] },
  { codigo: "CE", nombre: "Ceuta", fila: 5, columna: 3, alias: [] },
  { codigo: "ML", nombre: "Melilla", fila: 5, columna: 4, alias: [] },
];

const POR_NOMBRE = new Map<string, CasillaBase>(
  REJILLA.flatMap(({ alias, ...casilla }) =>
    [casilla.nombre, ...alias].map((nombre) => [foldText(nombre), casilla] as const),
  ),
);

/** La casilla de una comunidad, por su nombre o por una variante conocida. */
export function casillaDe(nombre: string): CasillaBase | null {
  return POR_NOMBRE.get(foldText(nombre).trim()) ?? null;
}

export interface Casilla extends CasillaBase {
  /** Peso de la comunidad en el importe de la empresa; `null` = sin adjudicaciones. */
  pct: number | null;
  contratos: number | null;
  /** Intensidad: 0 (vacía) a 5, relativa a la comunidad de más peso. */
  paso: number;
}

export interface FilaCcaa {
  label: string;
  ccaa?: string | null;
  contratos: number;
  cuota_empresa_pct: number;
}

/** Umbrales de los pasos 1 a 4, como fracción del máximo; por encima, el 5. */
const UMBRALES = [0.12, 0.3, 0.55, 0.85];

/**
 * En cuál de cinco pasos de intensidad cae un valor frente al máximo; 0 si no
 * hay nada que pintar. La comparten las casillas del perfil y la matriz
 * empresa × CCAA, para que el mismo tono signifique lo mismo en las dos.
 */
export function pasoIntensidad(valor: number, max: number): number {
  if (valor <= 0 || max <= 0) return 0;
  const razon = valor / max;
  const indice = UMBRALES.findIndex((umbral) => razon < umbral);
  return indice === -1 ? 5 : indice + 1;
}

/**
 * Las diecinueve casillas con el dato de cada una, y aparte las comunidades de
 * la respuesta que no encontraron casilla: no se dibujan, pero se dicen.
 */
export function buildCasillas(porCcaa: FilaCcaa[]): {
  casillas: Casilla[];
  sinCasilla: { nombre: string; pct: number; contratos: number }[];
} {
  const datos = new Map<string, FilaCcaa>();
  const sinCasilla: { nombre: string; pct: number; contratos: number }[] = [];
  for (const fila of porCcaa) {
    const nombre = fila.ccaa ?? fila.label;
    const casilla = casillaDe(nombre);
    if (casilla) datos.set(casilla.codigo, fila);
    else sinCasilla.push({ nombre, pct: fila.cuota_empresa_pct, contratos: fila.contratos });
  }
  const max = Math.max(0, ...[...datos.values()].map((fila) => fila.cuota_empresa_pct));
  const casillas = REJILLA.map(({ alias: _alias, ...casilla }) => {
    const fila = datos.get(casilla.codigo);
    return {
      ...casilla,
      pct: fila ? fila.cuota_empresa_pct : null,
      contratos: fila ? fila.contratos : null,
      paso: fila ? pasoIntensidad(fila.cuota_empresa_pct, max) : 0,
    };
  });
  return { casillas, sinCasilla };
}
