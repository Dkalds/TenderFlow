"use client";

/**
 * Claves de API de toda la instancia: la lista, su recuento y la revocación.
 *
 * Ajustes enseña las claves de quien mira; aquí están las de todos, también las
 * que no tienen dueño. Esas son las que motivaron la pantalla: en producción
 * había 89 activas sin usuario ni caducidad, que no se revocan al dar de baja a
 * nadie porque no son de nadie.
 *
 * El recuento (`resumen`) viene del servidor y se cuenta sobre la tabla entera:
 * la lista puede llegar recortada (`truncado`), y contar filas aquí daría una
 * cifra que no es la de la instancia.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { adminKeys } from "@/lib/query-keys";

export type ClaveInstancia = Schemas["AdminApiKeyOut"];
export type ClavesInstancia = Schemas["AdminApiKeysOut"];
type ClaveRevocada = Schemas["AdminApiKeyRevocadaOut"];

async function cargarClaves(): Promise<ClavesInstancia> {
  try {
    return await apiGet("/api/v1/admin/api-keys");
  } catch (error) {
    // Mismo criterio que `use-admin-users`: el 403 de la guarda llega en inglés.
    if (error instanceof ApiError && error.status === 403) {
      throw new ApiError(403, "Hace falta ser administrador");
    }
    throw error;
  }
}

export function useAdminApiKeys() {
  const queryClient = useQueryClient();

  const consulta = useQuery<ClavesInstancia>({
    queryKey: adminKeys.apiKeys,
    queryFn: cargarClaves,
    // El fallo se pinta en el panel: sin toast encima.
    meta: META_ERROR_EN_LINEA,
  });

  const revocar = useMutation({
    mutationFn: (keyId: number) => apiMutate<ClaveRevocada>("DELETE", `/api/v1/admin/api-keys/${keyId}`),
    onSuccess: (revocada) => {
      void queryClient.invalidateQueries({ queryKey: adminKeys.apiKeys });
      toast.success(`Clave «${revocada.name}» revocada: deja de valer al momento`);
    },
    // Un solo aviso: el global (`providers.tsx`) lo pinta con este título y el
    // `detail` de la API.
    meta: { errorTitle: "No se pudo revocar la clave" },
  });

  return {
    datos: consulta.data,
    isLoading: consulta.isLoading,
    error: consulta.error,
    reintentar: () => void consulta.refetch(),
    revocar,
  };
}
