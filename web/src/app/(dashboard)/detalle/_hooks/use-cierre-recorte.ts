"use client";

import { useCallback, useMemo } from "react";
import { parseAsString, useQueryStates } from "nuqs";
import { cierreLabel, cierreParams } from "../_lib/cierre";

// La parte pura (validación y rótulo) vive en `_lib/cierre.ts`; se reexporta
// porque la pantalla y sus tests la importan de aquí.
export { cierreLabel, cierreParams };

export interface CierreRecorte {
  /** Lo que se añade a la query de `GET /licitaciones`. */
  params: Record<string, string>;
  /** Texto del chip, o `null` cuando no hay recorte. */
  label: string | null;
  /** Quita el recorte de la URL. */
  clear: () => void;
}

/**
 * Lee el recorte por ventana de cierre de la URL.
 *
 * `shallow: true` e `history: "replace"` como el resto de los parámetros de la
 * pantalla: ningún Server Component los consume y quitar el recorte no merece
 * una entrada de historial propia.
 */
export function useCierreRecorte(): CierreRecorte {
  const [params, setParams] = useQueryStates(
    { cierre_desde: parseAsString, cierre_hasta: parseAsString },
    { history: "replace", shallow: true },
  );

  const apiParams = useMemo(
    () => cierreParams(params.cierre_desde, params.cierre_hasta),
    [params.cierre_desde, params.cierre_hasta],
  );

  const clear = useCallback(
    () => setParams({ cierre_desde: null, cierre_hasta: null }),
    [setParams],
  );

  return { params: apiParams, label: cierreLabel(apiParams), clear };
}
