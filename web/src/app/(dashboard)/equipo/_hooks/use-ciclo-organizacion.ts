/**
 * Salir, traspasar y borrar una organización (C2.2; CU-26).
 *
 * Los endpoints existían desde C2.2 sin ninguna pantalla. Viven aquí y no en
 * `hooks/use-organization.ts` porque solo los usa Equipo, y aquel módulo lo
 * importa media aplicación.
 *
 * Todas las mutaciones con `META_ERROR_EN_LINEA`: cuando la API se niega, el
 * motivo se pinta en el diálogo que pidió la acción, que es donde se lee.
 */
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiMutate, fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { organizationKeys } from "@/lib/claves-raiz";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { type Organization, useOrganizationStore } from "@/hooks/use-organization";

export type ResumenDeBorrado = Schemas["OrganizationDeletionSummary"];

/**
 * Bajo la raíz de organizaciones: salir, traspasar o borrar invalidan esa raíz,
 * y con ella cae también un recuento que ya no describe nada.
 */
const cicloKeys = {
  vistaPrevia: (organizationId: number) => [...organizationKeys.all, organizationId, "deletion-preview"] as const,
};

/**
 * Tras salir de una organización o borrarla, deja de ser la activa.
 *
 * Se quita del listado en caché **antes** de soltar la elección: si no, hasta
 * que `/organizations` contesta, la de por defecto se calcularía con la lista
 * vieja y podría volver a ser la misma, con un 403 en cada pantalla.
 */
function useOlvidarOrganizacion() {
  const queryClient = useQueryClient();
  const setActiveOrganizationId = useOrganizationStore((state) => state.setActiveOrganizationId);
  return (organizationId: number) => {
    queryClient.setQueryData<Organization[]>(organizationKeys.all, (anteriores) =>
      Array.isArray(anteriores) ? anteriores.filter((organizacion) => organizacion.id !== organizationId) : anteriores,
    );
    setActiveOrganizationId(null);
    void queryClient.invalidateQueries({ queryKey: organizationKeys.all });
  };
}

export function useSalirDeOrganizacion(organizacion: Organization) {
  const olvidar = useOlvidarOrganizacion();
  return useMutation({
    mutationFn: () => apiMutate<unknown>("POST", `/api/v1/organizations/${organizacion.id}/leave`),
    onSuccess: () => {
      toast.success(`Has salido de ${organizacion.name}`);
      olvidar(organizacion.id);
    },
    meta: META_ERROR_EN_LINEA,
  });
}

export function useTraspasarPropiedad(organizacion: Organization) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (nuevoOwnerUserId: number) =>
      apiMutate<unknown>("POST", `/api/v1/organizations/${organizacion.id}/transfer-ownership`, {
        nuevo_owner_user_id: nuevoOwnerUserId,
      }),
    onSuccess: () => {
      toast.success("Propiedad traspasada");
      // El rol de quien mira cambia (queda como administrador) y con él lo que
      // la pantalla le ofrece: el listado de organizaciones lo trae.
      void queryClient.invalidateQueries({ queryKey: organizationKeys.all });
      void queryClient.invalidateQueries({ queryKey: organizationKeys.members(organizacion.id) });
    },
    meta: META_ERROR_EN_LINEA,
  });
}

/** Lo que se llevaría el borrado. Solo se pide al abrir la confirmación. */
export function useVistaPreviaBorrado(organizationId: number, enabled: boolean) {
  return useQuery({
    queryKey: cicloKeys.vistaPrevia(organizationId),
    queryFn: ({ signal }) =>
      fetchWithAuth<ResumenDeBorrado>(`/api/v1/organizations/${organizationId}/deletion-preview`, { signal }),
    enabled,
    // El recuento cambia con el trabajo del equipo: el de hace cinco minutos
    // no es el que se va a borrar.
    staleTime: 0,
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Borra la organización. La API pide la palabra fija `BORRAR`; la persona ya
 * confirmó tecleando el nombre, que es lo que distingue cuál se borra.
 */
export function useBorrarOrganizacion(organizacion: Organization) {
  const olvidar = useOlvidarOrganizacion();
  return useMutation({
    mutationFn: () =>
      apiMutate<ResumenDeBorrado>("POST", `/api/v1/organizations/${organizacion.id}/delete`, {
        confirmacion: "BORRAR",
      }),
    onSuccess: () => {
      toast.success(`${organizacion.name} se ha borrado`);
      olvidar(organizacion.id);
    },
    meta: META_ERROR_EN_LINEA,
  });
}
