"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth, type ApiGetResult } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { empresasKeys } from "@/lib/query-keys";

/**
 * Consultas del maestro de empresas.
 *
 * Viven aparte de la pantalla porque el orden y la paginación son del
 * servidor, y eso obliga a que la clave de caché lleve dentro los cinco
 * parámetros que definen la página. Con la clave anterior (`["empresas", q]`)
 * cambiar de página o de columna devolvía el resultado cacheado de la
 * anterior: la tabla se quedaba quieta y parecía que el clic no había hecho
 * nada.
 */

export type EmpresaSortKey = "nombre" | "nif" | "contratos" | "importe";

// Las formas salen del esquema generado.
export type EmpresaRow = Schemas["EmpresaListItem"];
export type EmpresaDetail = Schemas["EmpresaDetail"];

/**
 * Lo que la ficha del maestro lee del perfil competitivo: sólo los totales, para
 * su línea de actividad. Trayectoria, rankings y cuotas son de la ficha de
 * Competencia, que el enlace «Abrir ficha» abre en «Todo el histórico»: pide
 * este mismo perfil sin filtros, así que las cifras coinciden.
 */
export type PerfilEmpresa = Schemas["CompetitiveCompanyProfileDTO"];

/** Filas por página del maestro. */
export const PAGE_SIZE = 12;

export function useEmpresasList({
  search,
  page,
  sort,
  order,
}: {
  search: string;
  page: number;
  sort: EmpresaSortKey;
  order: "asc" | "desc";
}) {
  return useQuery({
    queryKey: empresasKeys.list(search, page, sort, order),
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
        sort,
        order,
      });
      if (search) params.set("q", search);
      return fetchWithAuth<ApiGetResult<"/api/v1/empresas">>(`/api/v1/empresas?${params.toString()}`);
    },
    staleTime: 60 * 1000,
    // La página anterior se queda pintada mientras llega la siguiente, así que
    // ordenar o paginar no vacía la tabla y vuelve a llenarla: el salto de
    // altura era lo que hacía perder el sitio al ojo entre un clic y el
    // siguiente.
    placeholderData: (previous) => previous,
    // El fallo se dice en la propia columna (PanelError): sin toast además.
    meta: META_ERROR_EN_LINEA,
  });
}

export function useEmpresaDetail(empresaId: number | null) {
  return useQuery({
    queryKey: empresasKeys.detail(empresaId ?? 0),
    queryFn: () => fetchWithAuth<ApiGetResult<"/api/v1/empresas/{empresa_id}">>(`/api/v1/empresas/${empresaId}`),
    enabled: empresaId != null,
    meta: META_ERROR_EN_LINEA,
  });
}

export function useEmpresaPerfil(empresaId: number | null) {
  return useQuery({
    queryKey: empresasKeys.perfil(empresaId ?? 0),
    queryFn: () =>
      fetchWithAuth<ApiGetResult<"/api/v1/competitive/empresas/{empresa_id}/perfil">>(
        `/api/v1/competitive/empresas/${empresaId}/perfil`,
      ),
    enabled: empresaId != null,
    // La ficha dice «No se pudo cargar la actividad» en su línea.
    meta: META_ERROR_EN_LINEA,
  });
}
