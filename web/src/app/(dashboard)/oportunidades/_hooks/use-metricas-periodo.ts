"use client";

/**
 * `GET /pursuits/metrics` con la ventana que elige Rendimiento.
 *
 * Por qué vive aquí y no en `hooks/use-pursuits.ts`: `usePursuitMetrics` pide
 * las métricas **sin periodo** y lo consumen el tablero y otras superficies
 * que no tienen selector. El único sitio que elige ventana es esta vista, así
 * que el parámetro vive con ella. Si algún día el hook compartido acepta
 * periodo, éste sobra y se borra: son la misma petición.
 *
 * La clave sale de `@/lib/query-keys` —no se escribe a mano— y está montada
 * para que **sin periodo sea exactamente la de `usePursuitMetrics`**: mismo
 * dato, misma entrada de caché, una sola petición. Con periodo, una entrada
 * por ventana.
 */
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api-client";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { pursuitKeys } from "@/lib/query-keys";
import type { RangoPeriodo } from "../_lib/periodo";

export function useMetricasPeriodo(rango: RangoPeriodo) {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: pursuitKeys.metricsPeriodo(organizationId, rango.desde, rango.hasta),
    queryFn: () =>
      apiGet("/api/v1/pursuits/metrics", {
        params: {
          query: {
            organization_id: organizationId ?? undefined,
            // `undefined` lo descarta el serializador del cliente tipado, así
            // que «histórico» manda la misma URL que mandaba antes el hook sin
            // periodo — y por eso puede compartir su entrada de caché.
            period_from: rango.desde ?? undefined,
            period_to: rango.hasta ?? undefined,
          },
        },
      }),
    enabled: organizacionResuelta(organizationId),
    staleTime: 60_000,
  });
}
