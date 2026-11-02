"use client";

/**
 * El expediente completo, por id.
 *
 * Existe porque la ficha de una oportunidad y el inspector de Detalle son la
 * misma licitación vista desde dos sitios: hasta 2026-09 el contenido del
 * expediente sólo vivía en `/detalle` y la oportunidad —donde se decide— sólo
 * enlazaba a él. Quien decidía miraba una pantalla y leía la otra.
 *
 * El tipo sale del esquema generado, no se copia a mano: un campo que la API
 * deje de enviar rompe el typecheck aquí y no la pantalla.
 */
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import type { GoNoGoChecklist } from "@/hooks/use-pursuit-checklist";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { HistorialPropio, LicitacionDetail, NovedadesDeFicha, SimilaresResult } from "@/lib/api-types";
import { licitacionKeys } from "@/lib/query-keys";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";

export { licitacionKeys } from "@/lib/query-keys";

export function useLicitacion(id: string | null) {
  return useQuery({
    queryKey: licitacionKeys.detail(id ?? ""),
    queryFn: () =>
      fetchWithAuth<LicitacionDetail>(`/api/v1/licitaciones/${encodeURIComponent(id!)}`),
    enabled: Boolean(id),
    // El expediente cambia con la pasada de ingesta (cada 4 h), no entre
    // pestañas: revalidar en cada foco sería tráfico sin información nueva.
    staleTime: 5 * 60 * 1000,
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Expedientes parecidos a este (`GET /licitaciones/{id}/similares`, C1.3).
 *
 * Existía sin ningún consumidor. La respuesta trae también el predecesor, pero
 * ése ya lo enseña la competencia esperada como incumbente; aquí se usan los
 * parecidos, con el `metodo` y el `n` que dicen cómo leerlos.
 */
export function useSimilares(id: string | null, limite = 5) {
  return useQuery({
    queryKey: licitacionKeys.similares(id ?? "", limite),
    queryFn: ({ signal }) =>
      fetchWithAuth<SimilaresResult>(
        `/api/v1/licitaciones/${encodeURIComponent(id!)}/similares?limit=${limite}`,
        { signal },
      ),
    enabled: Boolean(id),
    staleTime: 5 * 60 * 1000,
    meta: META_ERROR_EN_LINEA,
  });
}

/** `?organization_id=` de la organización activa, o nada si es la personal. */
function conOrganizacion(url: string, organizationId: number | null | undefined): string {
  return organizationId != null ? `${url}?organization_id=${organizationId}` : url;
}

/**
 * «¿Cumplo?» del expediente (`GET /licitaciones/{id}/checklist`).
 *
 * El mismo contraste que el checklist de una oportunidad, antes de abrirla.
 * Como allí, se contrasta con la capacidad de la organización activa: la
 * clave la lleva y la consulta espera a saber cuál es.
 */
export function useChecklistLicitacion(id: string | null) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...licitacionKeys.checklist(id ?? ""), organizationId],
    queryFn: ({ signal }) =>
      fetchWithAuth<GoNoGoChecklist>(
        conOrganizacion(`/api/v1/licitaciones/${encodeURIComponent(id!)}/checklist`, organizationId),
        { signal },
      ),
    enabled: Boolean(id) && organizacionResuelta(organizationId),
    staleTime: 5 * 60 * 1000,
    meta: META_ERROR_EN_LINEA,
  });
}

/** Lo que tu organización ha ganado con el órgano y en el CPV del expediente. */
export function useHistorialPropio(id: string | null) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: [...licitacionKeys.historialPropio(id ?? ""), organizationId],
    queryFn: ({ signal }) =>
      fetchWithAuth<HistorialPropio>(
        conOrganizacion(`/api/v1/licitaciones/${encodeURIComponent(id!)}/historial-propio`, organizationId),
        { signal },
      ),
    enabled: Boolean(id) && organizacionResuelta(organizationId),
    staleTime: 5 * 60 * 1000,
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Registra la visita a la ficha y devuelve qué cambió desde la anterior
 * (`POST /licitaciones/{id}/visita`).
 *
 * Una sola vez por expediente y montaje: la llamada mueve la marca, así que
 * repetirla —el doble efecto de StrictMode, un re-render— dejaría la franja
 * vacía. Un fallo no avisa: la franja es un añadido y sin ella la ficha
 * sigue entera.
 */
export function useVisitaFicha(id: string): NovedadesDeFicha | null {
  const [visita, setVisita] = React.useState<NovedadesDeFicha | null>(null);
  const registrada = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (registrada.current === id) return;
    registrada.current = id;
    setVisita(null);
    apiMutate<NovedadesDeFicha>("POST", `/api/v1/licitaciones/${encodeURIComponent(id)}/visita`)
      .then((respuesta) => {
        if (registrada.current === id) setVisita(respuesta);
      })
      .catch(() => undefined);
  }, [id]);
  return visita;
}
