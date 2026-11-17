"use client";

import { useQuery } from "@tanstack/react-query";

import { organizacionResuelta, type OrganizacionActiva } from "@/hooks/use-organization";
import { apiGet } from "@/lib/api-client";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { pursuitKeys } from "@/lib/query-keys";

/** Carga del equipo (`GET /pursuits/direccion/carga`): los recuentos los da el backend. */
export function useCargaEquipo(organizationId: OrganizacionActiva) {
  return useQuery({
    queryKey: pursuitKeys.direccionCarga(organizationId),
    queryFn: () =>
      apiGet("/api/v1/pursuits/direccion/carga", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    enabled: organizacionResuelta(organizationId),
    retry: false,
    meta: META_ERROR_EN_LINEA,
  });
}
