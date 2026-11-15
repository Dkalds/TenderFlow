"use client";

/**
 * Colas de revisión del dato (`/admin/revision/*`): duplicados por decidir
 * (ADR-026), órganos por decidir (ADR-032 §C) y el panel de verdad del dato.
 *
 * Las dos colas siguen el mismo patrón: decidir avisa con el `detalle` del
 * servidor, refresca su cola y la calidad (los recuentos cambian), y un fallo
 * también refresca la cola —un 404 es que otra persona ya lo decidió—. El
 * error de la mutación lo dice el toast global con su `errorTitle`; el de la
 * lectura, el panel (`META_ERROR_EN_LINEA`).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { adminKeys, analyticsKeys } from "@/lib/query-keys";
import { toast } from "@/lib/toast";

type DuplicadosPendientes = Schemas["DuplicadosPendientes"];
type OrganosPendientes = Schemas["OrganosPendientes"];
type VerdadDominio = Schemas["VerdadDominio"];

/** Lo que se pide de cada cola: cabe de sobra en un turno de revisión. */
const LIMITE_COLA = 50;

export function useDuplicadosPendientes() {
  return useQuery<DuplicadosPendientes>({
    queryKey: adminKeys.revision.duplicados,
    queryFn: () =>
      apiGet("/api/v1/admin/revision/duplicados", {
        params: { query: { limit: LIMITE_COLA } },
      }) as Promise<DuplicadosPendientes>,
    meta: META_ERROR_EN_LINEA,
  });
}

/** `aceptar`: es el mismo contrato y sale también de las métricas. */
export function useResolverDuplicado() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, aceptar }: { id: string; aceptar: boolean }) =>
      apiMutate<Schemas["DuplicadoResuelto"]>(
        "POST",
        `/api/v1/admin/revision/duplicados/${encodeURIComponent(id)}/resolver`,
        { aceptar },
      ),
    onSuccess: (res) => {
      toast.success(res.detalle);
      void queryClient.invalidateQueries({ queryKey: adminKeys.revision.duplicados });
      void queryClient.invalidateQueries({ queryKey: analyticsKeys.quality });
    },
    meta: { errorTitle: "No se pudo resolver el par" },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.revision.duplicados });
    },
  });
}

export function useOrganosPendientes() {
  return useQuery<OrganosPendientes>({
    queryKey: adminKeys.revision.organos,
    queryFn: () =>
      apiGet("/api/v1/admin/revision/organos", {
        params: { query: { limit: LIMITE_COLA } },
      }) as Promise<OrganosPendientes>,
    meta: META_ERROR_EN_LINEA,
  });
}

/** `aceptar`: la grafía pasa a ser otro nombre del órgano conocido. */
export function useResolverOrgano() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, aceptar }: { id: number; aceptar: boolean }) =>
      apiMutate<Schemas["OrganoResuelto"]>("POST", `/api/v1/admin/revision/organos/${id}/resolver`, { aceptar }),
    onSuccess: (res) => {
      toast.success(res.detalle);
      void queryClient.invalidateQueries({ queryKey: adminKeys.revision.organos });
      void queryClient.invalidateQueries({ queryKey: analyticsKeys.quality });
    },
    meta: { errorTitle: "No se pudo resolver la revisión" },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.revision.organos });
    },
  });
}

export function useVerdadDominio() {
  return useQuery<VerdadDominio>({
    queryKey: adminKeys.revision.verdad,
    queryFn: () => apiGet("/api/v1/admin/revision/verdad") as Promise<VerdadDominio>,
    // La medición es cara y se renueva cada hora: no se repite al volver a la pestaña.
    staleTime: 15 * 60 * 1000,
    meta: META_ERROR_EN_LINEA,
  });
}
