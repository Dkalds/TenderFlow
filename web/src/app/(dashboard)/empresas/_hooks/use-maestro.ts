"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
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

export interface EmpresaRow {
  empresa_id: number;
  nombre_canonico: string;
  nif_canonico: string | null;
  es_ute: number;
  es_pyme: number | null;
  grupo: string | null;
  n_adjudicaciones: number;
  importe_total: number;
}

export interface EmpresasListResponse {
  items: EmpresaRow[];
  limit: number;
  offset: number;
  total: number;
}

export interface EmpresaDetail {
  empresa_id: number;
  nombre_canonico: string;
  nif_canonico: string | null;
  es_ute: number;
  es_pyme: number | null;
  grupo: string | null;
  aliases: { alias_normalizado: string; nif_variante: string | null; fuente: string | null }[];
  ute_miembros: { empresa_id: number; nombre_canonico: string }[];
  participa_en_utes: { empresa_id: number; nombre_canonico: string }[];
}

/**
 * Lo que la ficha del maestro lee del perfil competitivo: sólo los totales, para
 * su línea de actividad. Trayectoria, rankings y cuotas son de la ficha de
 * Competencia, que el enlace «Abrir ficha» abre en «Todo el histórico»: pide
 * este mismo perfil sin filtros, así que las cifras coinciden.
 */
export interface PerfilEmpresa {
  totales: {
    contratos: number;
    importe_total: number;
    primera_adjudicacion: string | null;
    ultima_adjudicacion: string | null;
  };
}

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
  return useQuery<EmpresasListResponse>({
    queryKey: empresasKeys.list(search, page, sort, order),
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
        sort,
        order,
      });
      if (search) params.set("q", search);
      return fetchWithAuth(`/api/v1/empresas?${params.toString()}`);
    },
    staleTime: 60 * 1000,
    // La página anterior se queda pintada mientras llega la siguiente, así que
    // ordenar o paginar no vacía la tabla y vuelve a llenarla: el salto de
    // altura era lo que hacía perder el sitio al ojo entre un clic y el
    // siguiente.
    placeholderData: (previous) => previous,
  });
}

export function useEmpresaDetail(empresaId: number | null) {
  return useQuery<EmpresaDetail>({
    queryKey: empresasKeys.detail(empresaId ?? 0),
    queryFn: () => fetchWithAuth(`/api/v1/empresas/${empresaId}`),
    enabled: empresaId != null,
  });
}

export function useEmpresaPerfil(empresaId: number | null) {
  return useQuery<PerfilEmpresa>({
    queryKey: empresasKeys.perfil(empresaId ?? 0),
    queryFn: () => fetchWithAuth(`/api/v1/competitive/empresas/${empresaId}/perfil`),
    enabled: empresaId != null,
  });
}
