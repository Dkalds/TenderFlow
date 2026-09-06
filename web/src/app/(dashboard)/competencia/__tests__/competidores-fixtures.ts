/**
 * Los tres competidores de referencia de las pruebas de esta pantalla.
 *
 * Están aquí y no en cada fichero porque los cuatro tests de Competidores
 * hablan del mismo mercado: si ACME deja de ser el líder en un sitio y no en
 * otro, las expectativas dejan de compararse entre sí.
 *
 * ACME tiene todas las métricas; BETA todas menos ninguna, con `pct_monopolio`
 * a 0 —un dato, no una ausencia—; GAMMA es el caso incompleto a propósito: sin
 * baja media ni importe medio, que es lo que el posicionamiento descarta.
 */

import type { Competitor } from "../_hooks/competidores-types";

export function competitor(over: Partial<Competitor> & { nombre: string }): Competitor {
  return { count: 0, importe: 0, cuota: 0, ...over };
}

export const ACME = competitor({
  nombre: "Acme Sistemas",
  nif: "A11111111",
  count: 10,
  importe: 1_000_000,
  cuota: 40,
  contratos_por_anio: 5,
  importe_medio: 100_000,
  baja_media: 20,
  pct_monopolio: 10,
});

export const BETA = competitor({
  nombre: "Beta Consulting",
  nif: "B22222222",
  count: 4,
  importe: 400_000,
  cuota: 16,
  contratos_por_anio: 2,
  importe_medio: 100_000,
  baja_media: 5,
  pct_monopolio: 0,
});

export const GAMMA = competitor({
  nombre: "Gamma Redes",
  nif: "C33333333",
  count: 7,
  importe: 200_000,
  cuota: 8,
});
