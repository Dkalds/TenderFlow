"use client";

/**
 * La selección de familias y fabricantes de cada expediente de la cola.
 *
 * Una lista ordenada por `id_externo` (la primera es la principal) que,
 * mientras nadie la toca, es la propuesta del LLM (`seleccionInicial`). Vive
 * aparte de `use-active-learning.ts`, que la expone, para que aquel quepa en
 * las 300 líneas de `src/app/**`; las operaciones sobre la lista son las
 * funciones puras de `_lib/active-learning.ts`.
 */

import { useCallback, useState } from "react";
import { alternarEtiqueta, hacerPrincipal, seleccionInicial, type QueueItem } from "../_lib/active-learning";

export interface SeleccionEtiquetas {
  /** Selección vigente de un expediente: la primera es la principal. */
  seleccionDe: (expediente: string) => string[];
  /** El clic en un chip del modelo: principal, o alternar con shift. */
  selectTech: (expediente: string, tech: string, shiftKey: boolean) => void;
  /** Marca o desmarca una etiqueta del selector de la taxonomía. */
  toggleTech: (expediente: string, codigo: string) => void;
  clearSelection: (expediente: string) => void;
}

export function useSeleccionEtiquetas(items: QueueItem[]): SeleccionEtiquetas {
  // Solo las selecciones que alguien ha editado; el resto es la propuesta.
  const [seleccion, setSeleccion] = useState<Record<string, string[]>>({});

  const inicialDe = useCallback(
    (expediente: string) => seleccionInicial(items.find((it) => it.id_externo === expediente)),
    [items],
  );

  const seleccionDe = useCallback(
    (expediente: string) => seleccion[expediente] ?? inicialDe(expediente),
    [seleccion, inicialDe],
  );

  // Desde `prev`: dos cambios antes de volver a pintar se suman, no se pisan.
  const editar = useCallback(
    (expediente: string, cambio: (actual: string[]) => string[]) =>
      setSeleccion((prev) => ({ ...prev, [expediente]: cambio(prev[expediente] ?? inicialDe(expediente)) })),
    [inicialDe],
  );

  const selectTech = useCallback(
    (expediente: string, tech: string, shiftKey: boolean) =>
      editar(expediente, (actual) => (shiftKey ? alternarEtiqueta(actual, tech) : hacerPrincipal(actual, tech))),
    [editar],
  );

  const toggleTech = useCallback(
    (expediente: string, codigo: string) => editar(expediente, (actual) => alternarEtiqueta(actual, codigo)),
    [editar],
  );

  const clearSelection = useCallback((expediente: string) => {
    setSeleccion((prev) => ({ ...prev, [expediente]: [] }));
  }, []);

  return { seleccionDe, selectTech, toggleTech, clearSelection };
}
