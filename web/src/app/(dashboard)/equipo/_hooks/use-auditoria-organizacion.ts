"use client";

/**
 * Rastro de auditoría de la organización (`GET /organizations/{id}/audit`).
 *
 * Paginado por el cursor opaco que devuelve el backend, del evento más
 * reciente al más antiguo; las fechas acotan por día en UTC (las dos
 * incluidas). Solo propietario y administrador: un miembro recibe 403, y la
 * pantalla ni siquiera monta el panel para él.
 *
 * El CSV es la misma consulta con `formato=csv`: lo arma el backend, que
 * neutraliza las celdas activas (`shared/export_safety.py`), y no la pantalla
 * a partir de lo que tiene cargado.
 */

import { useInfiniteQuery } from "@tanstack/react-query";

import { fetchBlobWithAuth, fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { gobiernoOrgKeys } from "@/lib/query-keys";

export type EntradaAuditoria = Schemas["AuditEntryOut"];
type PaginaAuditoria = Schemas["CursorPaginatedResponse_AuditEntryOut_"];

/** Eventos por página de la tabla. */
export const PAGINA_AUDITORIA = 50;
/**
 * Eventos por CSV: el `MAX_PAGE_LIMIT` de la API. Una exportación más larga
 * son varias páginas; el panel avisa cuando el fichero llega al tope.
 */
export const TOPE_CSV_AUDITORIA = 500;

export interface RangoAuditoria {
  desde: string | null;
  hasta: string | null;
}

export function urlAuditoria(
  organizationId: number,
  rango: RangoAuditoria,
  extra: Record<string, string> = {},
): string {
  const params = new URLSearchParams();
  if (rango.desde) params.set("desde", rango.desde);
  if (rango.hasta) params.set("hasta", rango.hasta);
  for (const [clave, valor] of Object.entries(extra)) params.set(clave, valor);
  const query = params.toString();
  return `/api/v1/organizations/${organizationId}/audit${query ? `?${query}` : ""}`;
}

export function useAuditoriaOrganizacion(organizationId: number, rango: RangoAuditoria, enabled = true) {
  return useInfiniteQuery({
    // `enabled: false` con un rango al revés: la API respondería 422.
    enabled,
    queryKey: gobiernoOrgKeys.auditoria(organizationId, rango.desde, rango.hasta),
    queryFn: ({ pageParam, signal }) =>
      fetchWithAuth<PaginaAuditoria>(
        urlAuditoria(organizationId, rango, {
          limit: String(PAGINA_AUDITORIA),
          ...(pageParam ? { cursor: pageParam } : {}),
        }),
        { signal },
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (pagina) => (pagina.has_more ? (pagina.next_cursor ?? undefined) : undefined),
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Filas de datos de un CSV, sin la cabecera. Cuenta saltos de línea fuera de
 * comillas: el `detail` puede llevar saltos dentro de una celda.
 */
export function filasDeCsv(texto: string): number {
  let filas = 0;
  let entreComillas = false;
  for (const letra of texto) {
    if (letra === '"') entreComillas = !entreComillas;
    else if (letra === "\n" && !entreComillas) filas += 1;
  }
  return Math.max(0, filas - 1);
}

/** El CSV del rango y cuántas filas trae, para saber si llegó al tope. */
export async function descargarCsvAuditoria(
  organizationId: number,
  rango: RangoAuditoria,
): Promise<{ blob: Blob; filas: number }> {
  const blob = await fetchBlobWithAuth(
    urlAuditoria(organizationId, rango, { formato: "csv", limit: String(TOPE_CSV_AUDITORIA) }),
  );
  return { blob, filas: filasDeCsv(await blob.text()) };
}
