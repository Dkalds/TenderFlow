"use client";

/**
 * El cuadro de Dirección para la organización activa y la ventana de la URL.
 *
 * El periodo vive en `?periodo=`, como en Rendimiento: una ventana concreta se
 * comparte y sobrevive a la recarga. Se escribe con `reemplazarQuery`
 * (`lib/url-superficial.ts`), sin navegar: ningún Server Component lee
 * `periodo`. Dirección entra por «12 meses» y no por el histórico porque su
 * pregunta es «vamos mejor o peor», y el histórico no tiene periodo anterior.
 * La ventana sólo se traduce a `period_from`/`period_to`: el recorte y la
 * comparación los hace el backend (ADR-014).
 */
import * as React from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { organizacionResuelta, type OrganizacionActiva } from "@/hooks/use-organization";
import { apiGet } from "@/lib/api-client";
import { periodoDeUrl, rangoDePeriodo, type PeriodoClave } from "@/lib/periodo";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { pursuitKeys } from "@/lib/query-keys";
import { queryActual, reemplazarQuery } from "@/lib/url-superficial";

export const PERIODO_DIRECCION: PeriodoClave = "12m";

export function useCuadroDireccion(organizationId: OrganizacionActiva) {
  const params = useSearchParams();
  const periodo = periodoDeUrl(params.get("periodo"), PERIODO_DIRECCION);
  // `rangoDePeriodo` trunca al día: la clave es la misma toda la sesión aunque
  // `new Date()` cambie en cada render (el porqué, en `lib/periodo.ts`).
  const rango = rangoDePeriodo(periodo, new Date());

  const cambiarPeriodo = React.useCallback((siguiente: PeriodoClave) => {
    const search = queryActual();
    // El de por defecto se quita del enlace: la URL canónica sigue siendo la corta.
    if (siguiente === PERIODO_DIRECCION) search.delete("periodo");
    else search.set("periodo", siguiente);
    reemplazarQuery(search);
  }, []);

  const consulta = useQuery({
    queryKey: pursuitKeys.direccion(organizationId, rango.desde, rango.hasta),
    queryFn: () =>
      apiGet("/api/v1/pursuits/direccion", {
        params: {
          query: {
            organization_id: organizationId ?? undefined,
            period_from: rango.desde ?? undefined,
            period_to: rango.hasta ?? undefined,
          },
        },
      }),
    // Sin `organization_id` el backend resuelve la organización **personal**, y
    // las oportunidades viven en la del equipo: no se pregunta antes de saberla.
    enabled: organizacionResuelta(organizationId),
    // Al cambiar de periodo se queda la ventana anterior a la vista hasta que
    // llega la nueva, en vez de volver al esqueleto; al cambiar de
    // organización, no: enseñaría las cifras de otro equipo.
    placeholderData: (anterior, consultaAnterior) =>
      consultaAnterior?.queryKey[2] === organizationId ? anterior : undefined,
    retry: false,
    // El fallo se pinta en la pantalla: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  return { periodo, cambiarPeriodo, ...consulta };
}
