/**
 * Los tres competidores de referencia de las pruebas de esta pantalla.
 *
 * Están aquí y no en cada fichero porque todos los tests de Competidores
 * hablan del mismo mercado: si ACME deja de ser el líder en un sitio y no en
 * otro, las expectativas dejan de compararse entre sí.
 *
 * ACME tiene todas las métricas; BETA también, con `pct_monopolio` a 0 —un
 * dato, no una ausencia—; GAMMA es el caso incompleto a propósito: sin baja
 * media ni importe medio, que es lo que la lente de precio del mapa descarta.
 *
 * El tipo es el generado del OpenAPI (`CompetitorEntry`), no uno escrito a
 * mano: si el backend renombra un campo, estas fixtures dejan de compilar.
 */

import type { Competitor } from "../_hooks/competidores-types";

export function competitor(over: Partial<Competitor> & { nombre: string }): Competitor {
  return {
    count: 0,
    importe: 0,
    cuota: 0,
    // Los cinco que el backend rellena con su valor por defecto.
    contratos_por_anio: 0,
    importe_medio: 0,
    n_organos: 0,
    pct_top_organo: 0,
    es_agrupacion: false,
    ...over,
  };
}

export const ACME = competitor({
  nombre: "Acme Sistemas",
  nif: "A11111111",
  empresa_id: 1,
  count: 10,
  importe: 1_000_000,
  cuota: 40,
  contratos_por_anio: 5,
  importe_medio: 100_000,
  baja_media: 20,
  ofertas_medias: 3.5,
  pct_monopolio: 10,
  n_organos: 6,
  pct_top_organo: 30,
});

export const BETA = competitor({
  nombre: "Beta Consulting",
  nif: "B22222222",
  empresa_id: 2,
  count: 4,
  importe: 400_000,
  cuota: 16,
  contratos_por_anio: 2,
  importe_medio: 100_000,
  baja_media: 5,
  ofertas_medias: 2,
  pct_monopolio: 0,
  n_organos: 2,
  pct_top_organo: 75,
});

export const GAMMA = competitor({
  nombre: "Gamma Redes",
  nif: "C33333333",
  count: 7,
  importe: 200_000,
  cuota: 8,
});
