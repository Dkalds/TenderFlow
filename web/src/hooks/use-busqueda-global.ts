"use client";

/**
 * F1.2 — la búsqueda de la paleta ⌘K (`GET /search/global`).
 *
 * Un término, cuatro clases de resultado: expedientes, empresas, órganos y
 * oportunidades de la organización activa. La paleta consulta mientras se
 * escribe, así que la petición sale **con debounce** y sólo a partir del mínimo
 * que el backend declara (tres caracteres): por debajo, el endpoint devuelve
 * `sin_busqueda` y no tiene sentido pedírselo en cada tecla.
 *
 * Sin organización activa no se buscan oportunidades, que no es lo mismo que
 * no encontrar ninguna: la respuesta lo declara en `tipos_buscados` y la
 * paleta lo repite en el vacío.
 */

import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "@/hooks/use-debounce";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { apiGet } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { searchKeys } from "@/lib/query-keys";

export type BusquedaGlobal = Schemas["BusquedaGlobal"];
export type ResultadoBusqueda = Schemas["ResultadoBusqueda"];
export type TipoResultado = ResultadoBusqueda["tipo"];

/** Mismo mínimo que `services/busqueda_global.MIN_LONGITUD`. */
export const MIN_LONGITUD_BUSQUEDA = 3;

/** Resultados por tipo: los que caben en una paleta sin hacer scroll. */
const LIMITE_POR_TIPO = 5;

/** Etiqueta de cada tipo, en singular, para el grupo y el lector de pantalla. */
export const ETIQUETA_TIPO: Record<TipoResultado, string> = {
  expediente: "Expediente",
  empresa: "Empresa",
  organo: "Órgano",
  oportunidad: "Oportunidad",
};

/** Plural para decir qué se buscó cuando no se encontró nada. */
export const PLURAL_TIPO: Record<string, string> = {
  expediente: "expedientes",
  empresa: "empresas",
  organo: "órganos",
  oportunidad: "oportunidades",
};

/**
 * A dónde lleva cada resultado.
 *
 * - Expediente: su ficha en Detalle.
 * - Empresa: el dossier del competidor, por su id del maestro.
 * - Órgano: el ranking de órganos con el filtro sembrado. Hasta que exista el
 *   maestro de órganos (C1.2) el id es el nombre normalizado, no una entidad
 *   con página propia; `organo_q` es el parámetro que la vista ya lee.
 * - Oportunidad: su ficha.
 */
export function destinoResultado(resultado: ResultadoBusqueda): string {
  switch (resultado.tipo) {
    case "expediente":
      return `/detalle?lic=${encodeURIComponent(resultado.id)}`;
    case "empresa":
      return `/competencia/empresa/${encodeURIComponent(resultado.id)}`;
    case "organo":
      return `/mercado?vista=organos&organo_q=${encodeURIComponent(resultado.titulo)}`;
    case "oportunidad":
      return `/oportunidades/${encodeURIComponent(resultado.id)}`;
  }
}

export function useBusquedaGlobal(termino: string) {
  const organizationId = useActiveOrganizationId();
  const q = useDebounce(termino.trim(), 250);
  const activa = q.length >= MIN_LONGITUD_BUSQUEDA;

  const query = useQuery<BusquedaGlobal>({
    queryKey: searchKeys.global(q, organizationId),
    queryFn: ({ signal }) =>
      apiGet("/api/v1/search/global", {
        params: {
          query: {
            q,
            limit: LIMITE_POR_TIPO,
            organization_id: organizationId ?? undefined,
          },
        },
        signal,
      }),
    enabled: activa && organizacionResuelta(organizationId),
    staleTime: 30_000,
    retry: false,
    // Un fallo aquí no es un incidente: la paleta sigue ofreciendo navegar y
    // mandar el texto a Detalle, que es lo que hacía antes de F1.2.
    meta: { silent: true },
  });

  return {
    /** Término con el que se hizo la búsqueda vigente (ya con debounce). */
    q,
    activa,
    /** El término tecleado aún no ha llegado al debounce. */
    pendiente: termino.trim() !== q,
    data: activa ? query.data : undefined,
    isFetching: activa && query.isFetching,
    isError: activa && query.isError,
  };
}
