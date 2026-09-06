"use client";

/**
 * Estado y datos del maestro de empresas: cobertura, buscador y selección.
 *
 * El texto del buscador se debounce a 300 ms antes de viajar, así que la clave
 * de caché es la consulta ya estabilizada y no cada tecla.
 */

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { fetchWithAuth } from "@/lib/api-client";
import { empresasKeys } from "@/lib/query-keys";
import { useDebounce } from "@/hooks/use-debounce";
import type { EmpresaRow, EmpresaStats, VistaMaestro } from "../_lib/types";

export function useEmpresasMaestro() {
  const searchParams = useSearchParams();
  // Deep-link externo: `?q=<empresa>` siembra la búsqueda.
  const [search, setSearch] = useState(() => searchParams?.get("q") ?? "");
  const debouncedSearch = useDebounce(search, 300);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [vista, setVista] = useState<VistaMaestro>("maestro");

  const { data: stats } = useQuery<EmpresaStats>({
    queryKey: empresasKeys.stats,
    queryFn: () => fetchWithAuth("/api/v1/empresas/stats"),
    staleTime: 5 * 60 * 1000,
  });

  const { data: list, isLoading } = useQuery<{ items: EmpresaRow[] }>({
    queryKey: empresasKeys.list(debouncedSearch),
    queryFn: () =>
      fetchWithAuth(
        `/api/v1/empresas?limit=50${debouncedSearch ? `&q=${encodeURIComponent(debouncedSearch)}` : ""}`,
      ),
    staleTime: 60 * 1000,
  });

  return {
    search,
    setSearch,
    selectedId,
    setSelectedId,
    vista,
    setVista,
    stats,
    items: list?.items ?? [],
    isLoading,
    pendientes: stats?.revisiones_pendientes ?? 0,
  };
}
