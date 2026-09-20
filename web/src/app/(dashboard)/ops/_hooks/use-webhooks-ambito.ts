"use client";

/**
 * Los dos ámbitos desde los que hoy se listan webhooks (S4.2).
 *
 * Un webhook dejó de ser un recurso de instancia: pertenece a una organización.
 * De ahí dos consultas y no una — la del equipo (`/equipo`) y la global de
 * administrador (`/ops`)—, cada una con su clave de caché, porque comparten
 * ruta base pero no conjunto de filas.
 *
 * No viven en `@/hooks/use-webhooks` porque ese módulo describe el listado de
 * instancia del cliente generado; cuando el codegen incorpore `organization_id`
 * y `formato`, estas dos se mudan allí sin tocar la pantalla.
 */

import { useQuery } from "@tanstack/react-query";
import { organizacionResuelta, type OrganizacionActiva } from "@/hooks/use-organization";
import { type WebhookOut } from "@/hooks/use-webhooks";
import { fetchWithAuth } from "@/lib/api-client";
import { webhookKeys } from "@/lib/query-keys";

/**
 * Campos que la API ya devuelve y el cliente generado todavía no describe
 * (`npm run codegen:file` los incorpora en cuanto se regenera desde el
 * OpenAPI de esta rama). Se declaran opcionales a propósito: la pantalla
 * compila y funciona con el cliente viejo y con el nuevo, y no hay que
 * duplicar la forma entera del DTO —que es el anti-patrón de ADR-014.
 */
export type WebhookAmpliado = WebhookOut & {
  organization_id?: number | null;
  created_by?: number | null;
  formato?: string | null;
};

/**
 * Webhooks de una organización (los que gestiona un equipo desde `/equipo`).
 *
 * Sin organización activa (`null`) sí se pide: es la lista sin ámbito. Lo que
 * no se hace es pedirla antes de saber cuál es, porque entonces la pestaña
 * enseñaría la lista personal medio segundo antes que la del equipo.
 */
export function useWebhooksDeEquipo(organizationId: OrganizacionActiva) {
  return useQuery({
    queryKey: [...webhookKeys.all, "organizacion", organizationId] as const,
    queryFn: () =>
      fetchWithAuth<WebhookAmpliado[]>(
        organizationId == null
          ? "/api/v1/webhooks"
          : `/api/v1/webhooks?organization_id=${organizationId}`,
      ),
    enabled: organizacionResuelta(organizationId),
    // Mismo motivo que la global: el error ya lo dice `Listado` en su sitio.
    meta: { silent: true },
  });
}

/** Todos los webhooks de la instancia. Solo administradores; vista de `/ops`. */
export function useWebhooksGlobales() {
  return useQuery({
    queryKey: [...webhookKeys.all, "global"] as const,
    queryFn: () => fetchWithAuth<WebhookAmpliado[]>("/api/v1/webhooks/global"),
    // `Listado` ya pinta el fallo en su sitio (`role="alert"`). El toast global
    // lo duplicaba, y para quien no es administrador —el 403 esperado de esta
    // ruta— era un error rojo por visitar una vista que solo puede leer.
    meta: { silent: true },
  });
}
