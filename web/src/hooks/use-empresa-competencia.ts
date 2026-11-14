"use client";

/**
 * Lo que el dossier de un competidor pide a la API (`components/competitors/`):
 * perfil, adjudicaciones, identidad en el maestro, cruces «contra mí» y socios
 * de UTE de un segmento. Cada fallo se dice en su panel (`PanelError`), así que
 * todas van con `META_ERROR_EN_LINEA`: sin toast además.
 */

import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import type {
  CompanyAward,
  CompanyAwardsData,
  CompanyProfileData,
} from "@/components/competitors/company-profile-types";
import { organizacionResuelta, useActiveOrganizationId } from "@/hooks/use-organization";
import { apiGet, fetchWithAuth } from "@/lib/api-client";
import type { Schemas } from "@/lib/api-types";
import { META_ERROR_EN_LINEA } from "@/lib/query-feedback";
import { competitiveKeys, empresasKeys } from "@/lib/query-keys";

/** Perfil competitivo con el ámbito y el periodo ya serializados (`scopeQuery`). */
export function usePerfilCompetidor(empresaId: number, scopeQuery: string) {
  return useQuery<CompanyProfileData>({
    queryKey: competitiveKeys.companyProfile(empresaId, scopeQuery),
    queryFn: () =>
      fetchWithAuth(`/api/v1/competitive/empresas/${empresaId}/perfil${scopeQuery ? `?${scopeQuery}` : ""}`),
    staleTime: 5 * 60 * 1000,
    // Cambiar de alcance o de periodo deja la ficha anterior, atenuada, hasta
    // que llega la nueva. Antes volvía al esqueleto de página entera, que se
    // llevaba también los botones recién pulsados. Sólo si es la misma
    // empresa: al saltar a otra (un socio de UTE), su nombre no puede ir
    // encima de las cifras de la anterior.
    placeholderData: (previo, consultaPrevia) => (consultaPrevia?.queryKey[1] === empresaId ? previo : undefined),
    meta: META_ERROR_EN_LINEA,
  });
}

const rutaAdjudicaciones = (empresaId: number, params: string) =>
  `/api/v1/competitive/empresas/${empresaId}/adjudicaciones?${params}`;

/** Una página de adjudicaciones; `params` ya lleva filtros, orden, `limit` y `offset`. */
export function useAdjudicacionesEmpresa(empresaId: number, params: string) {
  return useQuery<CompanyAwardsData>({
    queryKey: competitiveKeys.companyAwards(empresaId, params),
    queryFn: () => fetchWithAuth(rutaAdjudicaciones(empresaId, params)),
    placeholderData: keepPreviousData,
    // El fallo se dice en la tabla (PanelError), no como «no hay adjudicaciones».
    meta: META_ERROR_EN_LINEA,
  });
}

/**
 * Todas las adjudicaciones de los `filtros` (sin `limit` ni `offset`), para
 * exportarlas: pide páginas de 500 y sigue hasta `total`.
 */
export async function todasLasAdjudicaciones(empresaId: number, filtros: string): Promise<CompanyAward[]> {
  const pedirPagina = (offset: number) => {
    const params = new URLSearchParams(filtros);
    params.set("limit", "500");
    params.set("offset", String(offset));
    return fetchWithAuth<CompanyAwardsData>(rutaAdjudicaciones(empresaId, params.toString()));
  };
  const primera = await pedirPagina(0);
  const filas: CompanyAward[] = [...(primera.items ?? [])];
  // El paso es lo que devolvió la primera página: el backend puede recortar el `limit`.
  const paso = filas.length;
  const restantes: number[] = [];
  if (paso > 0) for (let o = paso; o < primera.total; o += paso) restantes.push(o);
  // De tres en tres: en paralelo, pero sin disparar decenas de peticiones a la vez.
  for (let i = 0; i < restantes.length; i += 3) {
    const paginas = await Promise.all(restantes.slice(i, i + 3).map(pedirPagina));
    for (const pagina of paginas) filas.push(...(pagina.items ?? []));
  }
  return filas;
}

/**
 * Ficha del maestro de cada identidad. Misma clave y misma petición que el
 * maestro (`useEmpresaDetail` en Competencia › Empresas): comparten caché.
 */
export function useIdentidadesEmpresa(empresaIds: number[]) {
  return useQueries({
    queries: empresaIds.map((empresaId) => ({
      queryKey: empresasKeys.detail(empresaId),
      queryFn: () => fetchWithAuth<Schemas["EmpresaDetail"]>(`/api/v1/empresas/${empresaId}`),
      staleTime: 5 * 60 * 1000,
      meta: META_ERROR_EN_LINEA,
    })),
  });
}

/** Cruces de las oportunidades presentadas del equipo con este competidor (F3.2). */
export function useBatallasContraMi(empresaKey: string, meses: number, empresaIds: readonly number[] = []) {
  const organizationId = useActiveOrganizationId();
  // Con una sola identidad no hay grupo que mandar: la ruta cruza la del path.
  const grupo = empresaIds.length > 1 ? empresaIds.join(",") : null;
  return useQuery<Schemas["BatallasContraMi"]>({
    queryKey: competitiveKeys.contraMi(empresaKey, organizationId, meses, grupo),
    // Ruta con parámetro de path: va por `fetchWithAuth` con el retorno tipado
    // desde el esquema generado (la regla de `apiGet` para rutas dinámicas).
    queryFn: () => {
      const query = new URLSearchParams({ meses: String(meses) });
      if (organizationId != null) query.set("organization_id", String(organizationId));
      if (grupo) query.set("empresa_ids", grupo);
      return fetchWithAuth<Schemas["BatallasContraMi"]>(
        `/api/v1/competitive/empresas/${encodeURIComponent(empresaKey)}/contra-mi?${query}`,
      );
    },
    // «Contra mí» es contra la organización activa: sin saber cuál es, la
    // comparación saldría contra la personal, que no ha competido con nadie.
    enabled: empresaKey.length > 0 && organizacionResuelta(organizationId),
    staleTime: 5 * 60_000,
    meta: META_ERROR_EN_LINEA,
  });
}

/** Socios y líderes de UTE de un segmento (F3.3). Sin prefijo CPV no hay segmento que pedir. */
export function useSociosUte(cpv: string | null, ccaa: string | null, limite: number) {
  return useQuery<Schemas["SugerenciaSocios"]>({
    queryKey: competitiveKeys.partners(cpv, ccaa),
    queryFn: () =>
      apiGet("/api/v1/competitive/partners", {
        params: { query: { cpv: cpv ?? undefined, ccaa: ccaa ?? undefined, limit: limite } },
      }),
    enabled: cpv != null,
    staleTime: 10 * 60_000,
    meta: META_ERROR_EN_LINEA,
  });
}
