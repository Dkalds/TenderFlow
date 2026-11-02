"use client";

import { useCallback } from "react";
import { parseAsString, useQueryState } from "nuqs";
import { PARAMETRO_DESDE, PARAMETRO_INTENCION, intencionDeTriaje } from "../_lib/triaje-resumen";

/**
 * La intención con la que se llegó desde el resumen diario
 * (`_lib/triaje-resumen.ts`), y cómo quitarla. Viaja en la URL y se quita con
 * `replace`, para que «atrás» no vuelva a ofrecer un triaje ya decidido.
 */
export function useTriajeResumen() {
  const [desde, setDesde] = useQueryState(PARAMETRO_DESDE, parseAsString.withOptions({ shallow: true }));
  const [intencionUrl, setIntencionUrl] = useQueryState(
    PARAMETRO_INTENCION,
    parseAsString.withOptions({ shallow: true }),
  );
  const cerrarTriaje = useCallback(() => {
    void setDesde(null, { history: "replace" });
    void setIntencionUrl(null, { history: "replace" });
  }, [setDesde, setIntencionUrl]);
  return { intencion: intencionDeTriaje(desde, intencionUrl), cerrarTriaje };
}
