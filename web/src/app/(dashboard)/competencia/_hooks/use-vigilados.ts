"use client";

/**
 * La petición de las empresas vigiladas y sus movimientos.
 *
 * La comparten el panel «Tus vigilados» y la vista, que con los ids marca esas
 * empresas en el mapa y en el ranking: misma clave, una sola petición.
 *
 * No depende del ámbito global a propósito: la watchlist es el ámbito, y una
 * señal «entra en Galicia» no puede desaparecer porque la barra filtre por
 * Madrid.
 */

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "@/lib/api-client";

import type { Movimientos } from "./vigilados";

/** Ventana de los movimientos, en días. */
export const DIAS_VIGILADOS = 30;

export function useMovimientosVigiladas() {
  return useQuery<Movimientos>({
    queryKey: ["competitive", "watchlist-movimientos", DIAS_VIGILADOS],
    queryFn: () =>
      apiGet("/api/v1/competitive/watchlist/movimientos", {
        params: { query: { dias: DIAS_VIGILADOS } },
      }) as Promise<Movimientos>,
    staleTime: 5 * 60 * 1000,
  });
}
