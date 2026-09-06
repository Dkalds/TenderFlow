"use client";

/**
 * Ficha de una empresa: identidad (aliases y UTEs) y perfil competitivo.
 *
 * Son dos endpoints distintos —`/empresas/{id}` y
 * `/competitive/empresas/{id}/perfil`— porque la identidad existe siempre y el
 * perfil solo si hay adjudicaciones enlazadas.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { empresasKeys } from "@/lib/query-keys";
import type { EmpresaDetail, PerfilEmpresa } from "../_lib/types";

export function useEmpresaPerfil(empresaId: number) {
  const { data: detail } = useQuery<EmpresaDetail>({
    queryKey: empresasKeys.detail(empresaId),
    queryFn: () => fetchWithAuth(`/api/v1/empresas/${empresaId}`),
  });

  const { data: perfil, isLoading } = useQuery<PerfilEmpresa>({
    queryKey: empresasKeys.perfil(empresaId),
    queryFn: () => fetchWithAuth(`/api/v1/competitive/empresas/${empresaId}/perfil`),
  });

  return { detail, perfil, isLoading };
}
