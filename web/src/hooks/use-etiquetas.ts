"use client";

/**
 * F1.6 — etiquetas de organización (D38).
 *
 * Libres, con color, hasta treinta por organización, aplicables a favoritos,
 * oportunidades y cuentas. Todo pasa por la organización activa: las
 * etiquetas son del equipo, y sin `organization_id` el backend resolvería la
 * personal, donde el equipo no tiene ninguna.
 *
 * `objeto_id` es la clave natural de cada tipo: el `id_externo` de la
 * licitación para un favorito, y el id numérico (como texto) para una
 * oportunidad o una cuenta.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiMutate } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import {
  organizacionResuelta,
  useActiveOrganizationId,
  type OrganizacionActiva,
} from "@/hooks/use-organization";
import { etiquetaKeys } from "@/lib/query-keys";
import { registrarEvento } from "@/lib/analytics";

export type Etiqueta = Schemas["Etiqueta"];
export type EtiquetaAplicada = Schemas["EtiquetaAplicada"];
export type ObjetoEtiquetable = Schemas["EtiquetaAplicacion"]["objeto_tipo"];

/** Tope de D38. El backend lo impone (409); aquí sólo se avisa antes. */
export const MAX_ETIQUETAS = 30;

/** Paleta cerrada: colores con contraste suficiente sobre fondo claro y oscuro. */
export const COLORES_ETIQUETA = [
  "#64748b",
  "#2563eb",
  "#0891b2",
  "#059669",
  "#ca8a04",
  "#ea580c",
  "#dc2626",
  "#9333ea",
] as const;

function conOrganizacion(url: string, organizationId: OrganizacionActiva): string {
  return organizationId != null ? `${url}?organization_id=${organizationId}` : url;
}

export function useEtiquetas() {
  const organizationId = useActiveOrganizationId();
  return useQuery({
    queryKey: etiquetaKeys.lista(organizationId),
    queryFn: () =>
      apiGet("/api/v1/etiquetas", {
        params: { query: { organization_id: organizationId ?? undefined } },
      }),
    enabled: organizacionResuelta(organizationId),
    staleTime: 60_000,
  });
}

/**
 * Etiquetas de una página de objetos, en una sola petición. `ids` vacío no
 * pide nada: la respuesta sería un mapa vacío y la petición, ruido.
 */
export function useEtiquetasDe(objetoTipo: ObjetoEtiquetable, ids: readonly string[]) {
  const organizationId = useActiveOrganizationId();
  const unicos = [...new Set(ids)].slice(0, 200);
  return useQuery({
    queryKey: etiquetaKeys.porObjeto(organizationId, objetoTipo, unicos),
    queryFn: async () => {
      const respuesta = await apiMutate<Schemas["EtiquetasPorObjeto"]>(
        "POST",
        conOrganizacion("/api/v1/etiquetas/por-objeto", organizationId),
        { objeto_tipo: objetoTipo, objeto_ids: unicos },
      );
      return respuesta.por_objeto ?? {};
    },
    enabled: unicos.length > 0 && organizacionResuelta(organizationId),
    staleTime: 30_000,
  });
}

export function useCrearEtiqueta() {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: (input: { nombre: string; color: string }) =>
      apiMutate<Etiqueta>("POST", conOrganizacion("/api/v1/etiquetas", organizationId), input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: etiquetaKeys.all }),
  });
}

export interface CambioEtiqueta {
  etiquetaId: number;
  objetoTipo: ObjetoEtiquetable;
  objetoId: string;
  aplicar: boolean;
}

/** Aplica o quita una etiqueta. Un solo hook para que el selector sea un toggle. */
export function useCambiarEtiqueta() {
  const queryClient = useQueryClient();
  const organizationId = useActiveOrganizationId();
  return useMutation({
    mutationFn: ({ etiquetaId, objetoTipo, objetoId, aplicar }: CambioEtiqueta) =>
      apiMutate<Schemas["ResultadoEtiquetado"]>(
        "POST",
        conOrganizacion(
          aplicar ? "/api/v1/etiquetas/aplicar" : "/api/v1/etiquetas/quitar",
          organizationId,
        ),
        { etiqueta_id: etiquetaId, objeto_tipo: objetoTipo, objeto_id: objetoId },
      ),
    onSuccess: (resultado, cambio) => {
      // Sólo lo que el servidor confirmó como cambio, y sólo `objeto`: el
      // nombre de la etiqueta lo escribe el usuario y no sale de aquí.
      if (cambio.aplicar && resultado.cambiado) {
        registrarEvento("etiqueta_aplicada", { objeto: cambio.objetoTipo });
      }
      return queryClient.invalidateQueries({ queryKey: etiquetaKeys.all });
    },
  });
}
