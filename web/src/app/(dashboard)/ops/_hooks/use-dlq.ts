"use client";

/**
 * Cola de errores de la ingesta (`/admin/dlq`): el listado por estado y sus dos
 * salidas, reencolar y descartar.
 *
 * Las dos salidas avisan con el `detalle` del servidor —en verde si hicieron
 * algo, informativo si no— y refrescan la cola en sus dos estados y la calidad,
 * de donde la tira de salud lee el recuento de la cola.
 */

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { adminKeys, analyticsKeys } from "@/lib/query-keys";
import { toast } from "@/lib/toast";

export type EstadoDlq = "abiertas" | "agotadas";
type DlqListado = Schemas["DlqListado"];

export function useDlq(estado: EstadoDlq) {
  return useQuery<DlqListado>({
    queryKey: adminKeys.dlq.estado(estado),
    queryFn: () => apiGet("/api/v1/admin/dlq", { params: { query: { estado, limit: 50 } } }) as Promise<DlqListado>,
    // El fallo (y el «sin permisos») se pinta en el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });
}

function avisarYRefrescar(queryClient: QueryClient, hecho: boolean, detalle: string) {
  if (hecho) toast.success(detalle);
  else toast.info(detalle);
  void queryClient.invalidateQueries({ queryKey: adminKeys.dlq.all });
  void queryClient.invalidateQueries({ queryKey: analyticsKeys.quality });
}

/** Devuelve la entrada al ciclo de reintentos: se reintenta en la próxima pasada, no al instante. */
export function useReencolarDlq() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiMutate<Schemas["DlqReintento"]>("POST", `/api/v1/admin/dlq/${id}/reintentar`),
    onSuccess: (res) => avisarYRefrescar(queryClient, res.reencolada, res.detalle),
    meta: { errorTitle: "No se pudo reencolar la entrada" },
  });
}

/** Cierra la entrada sin reintentarla. */
export function useDescartarDlq() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiMutate<Schemas["DlqDescarte"]>("POST", `/api/v1/admin/dlq/${id}/descartar`),
    onSuccess: (res) => avisarYRefrescar(queryClient, res.descartada, res.detalle),
    meta: { errorTitle: "No se pudo descartar la entrada" },
  });
}
