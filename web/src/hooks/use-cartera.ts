"use client";

/**
 * F4.3 — cartera de contratos en ejecución de la organización activa.
 *
 * Lleva `organization_id` siempre que haya una activa: sin él, el backend
 * resuelve la organización **personal**, y la cartera vive en la del equipo
 * (el mismo fallo que tuvo Dirección).
 */
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api-client";
import { useActiveOrganizationId } from "@/hooks/use-organization";
import { pursuitKeys } from "@/lib/query-keys";

export function useCartera() {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: pursuitKeys.cartera(organizationId),
    queryFn: () =>
      apiGet("/api/v1/pursuits/cartera", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    staleTime: 60_000,
  });
}
