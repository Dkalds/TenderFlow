"use client";

/**
 * Vista previa del Radar con el perfil que hay en pantalla, guardado o no.
 *
 * Pregunta a la API cómo quedarían las primeras oportunidades con esos pesos
 * y esos intereses (`POST /me/profile/preview`): el orden lo calcula quien
 * tiene el universo entero, no esta página. Va con retraso respecto a lo que
 * se teclea —un arrastre de deslizador son decenas de valores intermedios que
 * nadie quiere puntuar— y conserva la respuesta anterior mientras llega la
 * nueva, para que la lista no parpadee en cada ajuste.
 */

import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import type { ScoringPreview } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { perfilKeys } from "@/lib/query-keys";
import type { CuerpoPerfil } from "./use-perfil-scoring";

/** Espera tras el último cambio antes de pedir la vista previa. */
export const RETRASO_VISTA_PREVIA_MS = 600;

export function useVistaPrevia(cuerpo: CuerpoPerfil, { enabled }: { enabled: boolean }) {
  // `visibility` no cambia el orden: fuera de la clave, para que compartir o
  // dejar de compartir no cueste una petición.
  const pedido = JSON.stringify({ ...cuerpo, visibility: undefined });
  // `null` hasta que el formulario lleva quieto el retraso entero. La primera
  // petición también espera: al terminar de cargar, el formulario tarda un
  // render en recibir el perfil guardado, y pedir ya puntuaría los valores
  // por defecto para tirarlos un instante después.
  const [asentado, setAsentado] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const espera = setTimeout(() => setAsentado(pedido), RETRASO_VISTA_PREVIA_MS);
    return () => clearTimeout(espera);
  }, [enabled, pedido]);

  const consulta = useQuery({
    queryKey: perfilKeys.preview(cuerpo.organization_id, asentado ?? ""),
    queryFn: ({ signal }) =>
      fetchWithAuth<ScoringPreview>("/api/v1/me/profile/preview", {
        method: "POST",
        body: asentado,
        signal,
      }),
    enabled: enabled && asentado != null,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: false,
    meta: META_ERROR_EN_LINEA,
  });

  return {
    data: consulta.data,
    error: consulta.error,
    refetch: consulta.refetch,
    /** Todavía no hay ninguna respuesta que enseñar. */
    cargando: enabled && consulta.data === undefined && consulta.error == null,
    /** Lo que se enseña ya no corresponde a lo que hay en pantalla. */
    desfasada: enabled && consulta.data !== undefined && (asentado !== pedido || consulta.isFetching),
  };
}
