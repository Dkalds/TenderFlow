"use client";

import { useCallback } from "react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import type { ModoInspector } from "../../radar/_hooks/use-media-query";

/**
 * La ficha completa de /detalle: cuándo sustituye a la tabla.
 *
 * - Con `?ficha=completa` (el botón «Abrir la ficha completa» del inspector),
 *   en cualquier ancho. Entra en el historial: atrás vuelve al inspector.
 * - Siempre que haya una licitación abierta por debajo de `md` (modo
 *   `tarjeta`), donde no hay inspector: antes, abrir una fila en el móvil era
 *   un clic sin respuesta.
 */
export function useFichaCompleta({ modo, detailId }: { modo: ModoInspector; detailId: string | null }) {
  const [ficha, setFicha] = useQueryState(
    "ficha",
    parseAsStringLiteral(["completa"] as const).withOptions({ history: "push", shallow: true }),
  );
  const enMovil = modo === "tarjeta";
  const activa = Boolean(detailId) && (ficha === "completa" || enMovil);
  const abrir = useCallback(() => void setFicha("completa"), [setFicha]);
  const cerrar = useCallback(() => void setFicha(null, { history: "replace" }), [setFicha]);
  return { activa, enMovil, abrir, cerrar };
}

export interface PasoDeFicha {
  indice: number;
  id: string;
}

export interface PasosDeFicha {
  /** Posición de la abierta en la página; `null` si no está en ella (permalink). */
  posicion: { indice: number; total: number } | null;
  anterior: PasoDeFicha | null;
  siguiente: PasoDeFicha | null;
}

/**
 * La anterior y la siguiente de la licitación abierta, en el orden de la página
 * de la tabla. Una ficha abierta por permalink que no está en la página no
 * tiene vecinas: no se inventa un orden que la tabla no enseña.
 */
export function pasosDeFicha(
  filas: ReadonlyArray<{ id_externo: string }>,
  detailId: string | null,
): PasosDeFicha {
  const indice = detailId ? filas.findIndex((fila) => fila.id_externo === detailId) : -1;
  if (indice < 0) return { posicion: null, anterior: null, siguiente: null };
  const paso = (i: number): PasoDeFicha | null =>
    i >= 0 && i < filas.length ? { indice: i, id: filas[i].id_externo } : null;
  return {
    posicion: { indice, total: filas.length },
    anterior: paso(indice - 1),
    siguiente: paso(indice + 1),
  };
}
